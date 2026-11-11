"""Caption text and source-to-clip timeline mapping, without editorial rewriting."""
from __future__ import annotations

import math
import textwrap
from pathlib import Path


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def remap_cues(cues: list[dict], clip_start: float, clip_end: float, speed: float = 1.0) -> dict:
    """Intersect absolute source cues with a clip and report readability issues.

    No words are removed or invented when a cue intersects an edit boundary.
    The whole cue's text is retained for diagnosis, and every partial intersection
    is flagged. Callers must resolve boundary conflicts before approval/export.
    Editorial correction or translation belongs in the approved plan.
    """
    clip_start = _number(clip_start, "clip start")
    clip_end = _number(clip_end, "clip end")
    speed = _number(speed, "playback speed")
    if clip_start < 0 or clip_end <= clip_start or not 0.5 <= speed <= 2:
        raise ValueError("Invalid clip interval or playback speed (allowed 0.5–2)")
    if not isinstance(cues, list):
        raise ValueError("Caption cues must be a list")
    mapped, warnings = [], []
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("Each caption cue must be an object")
        start = _number(cue.get("start"), "cue start")
        end = _number(cue.get("end"), "cue end")
        text = cue.get("text")
        if start < 0 or end <= start or not isinstance(text, str) or not text.strip():
            raise ValueError("Caption cues need a nonnegative interval and nonempty text")
        if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
            raise ValueError("Caption text contains unsupported control characters")
        if end <= clip_start or start >= clip_end:
            continue
        relative_start = (max(start, clip_start) - clip_start) / speed
        relative_end = (min(end, clip_end) - clip_start) / speed
        plain = " ".join(text.split())
        lines = textwrap.wrap(plain, width=42, break_long_words=False, break_on_hyphens=False)
        mapped.append({"start": relative_start, "end": relative_end, "text": "\n".join(lines)})
        duration = relative_end - relative_start
        base = {"cue": index, "duration": round(duration, 3)}
        if start < clip_start or end > clip_end:
            warnings.append({**base, "code": "boundary_conflict", "source_start": start, "source_end": end,
                             "clip_start": clip_start, "clip_end": clip_end,
                             "message": "Caption cue crosses the clip boundary. Provide corrected source-aligned cues, choose a different clip, or set captions mode to none; the engine cannot infer which words belong inside the cut."})
        cps = len(plain) / duration
        if cps > 20:
            warnings.append({**base, "code": "reading_speed", "characters_per_second": round(cps, 2), "limit": 20})
        if duration < 0.8:
            warnings.append({**base, "code": "short_duration", "minimum_seconds": 0.8})
        if duration > 7:
            warnings.append({**base, "code": "long_duration", "maximum_seconds": 7})
        if len(lines) > 2:
            warnings.append({**base, "code": "too_many_lines", "lines": len(lines), "maximum_lines": 2})
        if any(len(line) > 42 for line in lines):
            warnings.append({**base, "code": "long_word", "maximum_characters_per_line": 42})
    mapped.sort(key=lambda cue: (cue["start"], cue["end"]))
    for index in range(1, len(mapped)):
        if mapped[index]["start"] < mapped[index - 1]["end"]:
            warnings.append({"code": "overlap", "cue": index})
    return {"cues": mapped, "warnings": warnings}


def caption_warnings(plan: dict, *, cues: list[dict] | None = None) -> list[dict]:
    """Inspect source-timeline captions before review and export."""
    captions = plan.get("captions", {})
    if captions.get("mode", "none") == "none":
        return []
    if cues is None:
        cues = captions.get("cues", [])
    return [{**warning, "clip": clip["id"]}
            for clip in plan["clips"]
            for warning in remap_cues(cues, clip["start"], clip["end"], plan.get("playback_speed", 1))["warnings"]]


def require_caption_boundaries(plan: dict, *, cues: list[dict] | None = None) -> None:
    """Reject partially retained cue text instead of guessing source word timing."""
    for warning in caption_warnings(plan, cues=cues):
        if warning["code"] == "boundary_conflict":
            raise PermissionError(f"Caption boundary conflict in clip {warning['clip']}, cue {warning['cue']} "
                                  f"(source {warning['source_start']}–{warning['source_end']}s; "
                                  f"clip {warning['clip_start']}–{warning['clip_end']}s). {warning['message']}")


def _timestamp(seconds: float, *, ass: bool = False) -> str:
    units = 100 if ass else 1000
    value = round(_number(seconds, "caption timestamp") * units)
    if value < 0:
        raise ValueError("Caption timestamps cannot be negative")
    seconds_whole, fraction = divmod(value, units)
    minutes_whole, seconds_whole = divmod(seconds_whole, 60)
    hours, minutes_whole = divmod(minutes_whole, 60)
    if ass:
        return f"{hours}:{minutes_whole:02}:{seconds_whole:02}.{fraction:02}"
    return f"{hours:02}:{minutes_whole:02}:{seconds_whole:02},{fraction:03}"


def write_srt(path: Path, cues: list[dict]) -> None:
    """Write UTF-8 editor-compatible captions; timestamps are already clip-relative."""
    blocks = [f"{index}\n{_timestamp(cue['start'])} --> {_timestamp(cue['end'])}\n{cue['text']}\n\n"
              for index, cue in enumerate(cues, 1)]
    Path(path).write_text("".join(blocks), encoding="utf-8")


def write_ass(path: Path, cues: list[dict], width: int, height: int, font: str = "Inter") -> None:
    """Write fixed styling as data; user text never enters FFmpeg's filter syntax."""
    size = max(10, round(min(width, height) * 0.048))
    margin = max(4, round(height * 0.05))
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,1,1,2,{margin},{margin},{margin},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for cue in cues:
        # libass understands escaped braces and backslashes; line breaks are explicit.
        text = cue["text"].replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_timestamp(cue['start'], ass=True)},{_timestamp(cue['end'], ass=True)},Default,,0,0,0,,{text}\n")
    Path(path).write_text(header + "".join(lines), encoding="utf-8")
