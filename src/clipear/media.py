"""Portable local media processing shared by the CLI and MCP service."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .captions import remap_cues, require_caption_boundaries, write_ass, write_srt


# Local sources must be self-contained camera/media containers. Playlist and
# reference demuxers can otherwise bypass input roots or fetch URLs from a file.
_LOCAL_INPUT = ["-protocol_whitelist", "file,pipe", "-format_whitelist",
                "mov,matroska,webm,avi,mpegts,mpeg,mxf,flv,ogg,asf,image2,png_pipe"]


class MediaError(RuntimeError):
    """A media dependency, source, encoding or verification failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _identifier(value, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError(f"Unsafe {name}: use 1–80 letters, digits, underscores or hyphens")
    return value


class Media:
    def __init__(self, settings):
        self.settings = settings

    def _run(self, arguments: list[str], directory: Path, stage: str, timeout: float | None = None) -> str:
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / f"{stage}-{uuid.uuid4().hex[:10]}.log"
        try:
            completed = subprocess.run([str(value) for value in arguments], cwd=directory,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=timeout, check=False)
            output = completed.stdout.decode("utf-8", errors="replace")
            log.write_text(output, encoding="utf-8")
        except (OSError, subprocess.TimeoutExpired) as error:
            log.write_text(str(error), encoding="utf-8")
            raise MediaError(f"{stage} could not run: {error}. See log: {log}") from error
        if completed.returncode:
            detail = output.strip()[-1500:]
            raise MediaError(f"{stage} failed (exit {completed.returncode}): {detail}. See log: {log}")
        return output

    def inspect(self, path: Path) -> dict:
        path = Path(path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise MediaError("Source must be a regular file")
        command = [str(self.settings.ffprobe), "-v", "error", *_LOCAL_INPUT, "-show_format", "-show_streams", "-of", "json", str(path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MediaError(f"ffprobe could not inspect the source: {error}") from error
        if completed.returncode:
            raise MediaError(f"ffprobe could not inspect the source: {completed.stderr.strip()[-1500:]}")
        try:
            data = json.loads(completed.stdout)
            streams = data.get("streams", [])
            video = next(stream for stream in streams if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic"))
            audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
            duration = float(data.get("format", {}).get("duration", video.get("duration", 0)))
            width, height = int(video["width"]), int(video["height"])
            rotation = next((float(side["rotation"]) for side in video.get("side_data_list", []) if "rotation" in side), 0)
            if round(rotation) % 180:
                width, height = height, width
            if not math.isfinite(duration) or duration < 0 or width <= 0 or height <= 0:
                raise ValueError("invalid dimensions/duration")
        except (ValueError, KeyError, TypeError, StopIteration) as error:
            raise MediaError(f"ffprobe returned no usable video stream: {path.name}") from error
        return {"duration": duration, "width": width, "height": height, "streams": streams,
                "has_audio": audio is not None, "video_codec": video.get("codec_name"),
                "pixel_format": video.get("pix_fmt"), "audio_codec": audio.get("codec_name") if audio else None,
                "sample_aspect_ratio": video.get("sample_aspect_ratio", "1:1"), "rotation": rotation}

    def _youtube_url(self, source: str) -> str:
        if any(ord(character) <= 32 for character in source):
            raise ValueError("YouTube URLs must not contain whitespace or control characters")
        try:
            parsed = urlsplit(source)
            hostname = parsed.hostname
            invalid_port = parsed.port is not None
        except ValueError as error:
            raise ValueError("Malformed YouTube URL") from error
        if (parsed.scheme not in ("https", "http") or invalid_port or parsed.username or parsed.password
                or hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be")):
            raise ValueError("Only ordinary YouTube video URLs are supported")
        if hostname in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.strip("/")
        elif parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.fullmatch(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?", parsed.path)
            video_id = match.group(1) if match else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("YouTube URL must identify one video")
        # Canonicalize to remove playlist and other non-video parameters.
        return f"https://www.youtube.com/watch?v={video_id}"

    def ingest(self, source: str, directory: Path) -> dict:
        if not isinstance(source, str) or not source or source.startswith("-") or "\x00" in source:
            raise ValueError("Provide a local camera path or one YouTube video URL")
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source):
            url = self._youtube_url(source)
            executable = str(self.settings.yt_dlp)
            command = [executable] if shutil.which(executable) else [sys.executable, "-m", "yt_dlp"]
            command += ["--ignore-config", "--no-playlist", "--no-progress", "--no-warnings", "--no-overwrites",
                        "--no-write-subs", "--no-write-auto-subs", "--no-write-thumbnail", "--no-write-info-json",
                        "--ffmpeg-location", shutil.which(str(self.settings.ffmpeg)) or str(Path(self.settings.ffmpeg).expanduser().resolve()),
                        "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mkv",
                        "-o", "source.%(ext)s", "--print", "after_move:filepath", "--", url]
            self._run(command, directory, "download", timeout=14400)
            files = [path for path in directory.glob("source.*") if path.is_file() and path.suffix not in (".part", ".ytdl")]
            if len(files) != 1:
                raise MediaError("YouTube download did not produce exactly one source file; inspect the download log")
            path = files[0].resolve()
            if not path.is_relative_to(directory):
                raise MediaError("Downloaded source escaped job storage")
        else:
            try:
                original = Path(source).expanduser().resolve(strict=True)
            except OSError as error:
                raise ValueError(f"Source file is inaccessible: {source}") from error
            if not original.is_file() or not any(original.is_relative_to(Path(root).expanduser().resolve()) for root in self.settings.input_roots):
                raise ValueError("Source file is outside configured input roots or is not a regular file")
            suffix = original.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", original.suffix) else ".media"
            path = directory / f"source{suffix.lower()}"
            if path.exists():
                raise MediaError("Job source already exists; use a new import job directory")
            before = _sha256(original)
            shutil.copyfile(original, path)
            if _sha256(original) != before or _sha256(path) != before:
                path.unlink(missing_ok=True)
                raise MediaError("Source changed during import; retry after the camera file stops changing")
        try:
            info = self.inspect(path)
        except MediaError as error:
            log = directory / f"inspect-{uuid.uuid4().hex[:10]}.log"
            log.write_text(str(error), encoding="utf-8")
            raise MediaError(f"Source import failed inspection. See log: {log}. {error}") from error
        return {"path": str(path), "sha256": _sha256(path), "info": info}

    def transcribe(self, path: Path, directory: Path, language: str = "auto", glossary: str = "") -> dict:
        info = self.inspect(path)
        if not info["has_audio"]:
            raise MediaError("Source has no audio stream to transcribe")
        if not self.settings.whisper_cli or not self.settings.whisper_model:
            raise MediaError("Configure a whisper.cpp CLI and existing model using CLIPEAR_WHISPER and CLIPEAR_MODEL")
        model = Path(self.settings.whisper_model).expanduser().resolve()
        if not model.is_file():
            raise MediaError("Configured whisper.cpp model does not exist; provide an existing model")
        if not isinstance(language, str) or not re.fullmatch(r"auto|[A-Za-z]{2,3}(?:-[A-Za-z]{2,8})?", language):
            raise ValueError("Transcription language must be auto or a language code")
        if not isinstance(glossary, str) or "\x00" in glossary:
            raise ValueError("Glossary must be text without null characters")
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        wav = directory / "audio.wav"
        self._run([self.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *_LOCAL_INPUT, "-i", str(Path(path).resolve()),
                   "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], directory, "extract-audio")
        prefix = directory / "transcript"
        command = [self.settings.whisper_cli, "-m", str(model), "-f", str(wav), "-l", language, "--output-json-full", "-of", str(prefix)]
        if glossary:
            command += ["--prompt", glossary]
        self._run(command, directory, "transcribe")
        evidence = prefix.with_suffix(".json")
        try:
            data = json.loads(evidence.read_text(encoding="utf-8"))
            segments = []
            for row in data["transcription"]:
                text = row["text"].strip()
                start, end = float(row["offsets"]["from"]) / 1000, float(row["offsets"]["to"]) / 1000
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                    raise ValueError("Invalid transcript timestamps")
                if text and end > start:
                    segments.append({"start": start, "end": end, "text": text})
            detected = data.get("result", {}).get("language", language)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise MediaError(f"whisper.cpp returned invalid transcript JSON. See evidence/logs in {directory}") from error
        return {"language": detected, "segments": segments, "path": str(evidence)}

    def _plan(self, path: Path, plan: dict) -> tuple[dict, str]:
        info = self.inspect(path)
        digest = _sha256(path)
        if plan.get("source_sha256") != digest:
            raise MediaError("Source fingerprint differs from the edit plan")
        speed = _finite(plan.get("playback_speed", 1), "playback speed")
        if not 0.5 <= speed <= 2:
            raise ValueError("Playback speed must be between 0.5 and 2")
        clips, profiles = plan.get("clips"), plan.get("outputs")
        if not isinstance(clips, list) or not clips or not isinstance(profiles, list) or not profiles:
            raise ValueError("Edit plan needs clips and output profiles")
        clip_ids, profile_ids = set(), set()
        for clip in clips:
            identifier = _identifier(clip.get("id"), "clip id")
            if identifier in clip_ids:
                raise ValueError("Duplicate clip id")
            clip_ids.add(identifier)
            start, end = _finite(clip.get("start"), "clip start"), _finite(clip.get("end"), "clip end")
            if start < 0 or end <= start or end > info["duration"] + 0.001:
                raise ValueError("Clip interval is outside the source duration")
        for profile in profiles:
            identifier = _identifier(profile.get("name"), "output name")
            if identifier in profile_ids:
                raise ValueError("Duplicate output profile name")
            profile_ids.add(identifier)
            self._framing(info, profile)
        if plan.get("quality", "balanced") not in ("fast", "balanced", "quality"):
            raise ValueError("Unknown encoding quality")
        delivery = plan.get("delivery", "clean")
        mode = plan.get("captions", {}).get("mode", "none")
        if delivery not in ("clean", "finished", "both") or mode not in ("none", "sidecar", "burn"):
            raise ValueError("Unknown delivery or caption mode")
        if mode == "burn" and delivery == "clean":
            raise ValueError("Burned captions require finished or both delivery")
        return info, digest

    @staticmethod
    def _framing(info: dict, profile: dict) -> tuple[str, int, int]:
        ratio, height = profile.get("ratio", "source"), profile.get("height", info["height"])
        if isinstance(height, bool) or not isinstance(height, int) or height < 32 or height > 4320 or height % 2:
            raise ValueError("Output height must be an even integer between 32 and 4320")
        if ratio == "source":
            try:
                numerator, denominator = (float(part) for part in info.get("sample_aspect_ratio", "1:1").split(":"))
                sar = numerator / denominator if numerator > 0 and denominator > 0 else 1
            except (ValueError, ZeroDivisionError):
                sar = 1
            aspect = info["width"] * sar / info["height"]
        elif ratio in ("16:9", "9:16", "1:1", "4:5"):
            numerator, denominator = (int(part) for part in ratio.split(":"))
            aspect = numerator / denominator
        else:
            raise ValueError("Unsupported output ratio")
        width = max(2, round(height * aspect / 2) * 2)
        fit, position = profile.get("fit", "pad"), profile.get("position", "center")
        if fit not in ("pad", "crop") or position not in ("left", "center", "right"):
            raise ValueError("Output fit/position must be pad/crop and left/center/right")
        if fit == "pad":
            x = {"left": "0", "center": "(ow-iw)/2", "right": "ow-iw"}[position]
            framing = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                       f"pad={width}:{height}:{x}:(oh-ih)/2:color=black,setsar=1")
        else:
            x = {"left": "0", "center": "(iw-ow)/2", "right": "iw-ow"}[position]
            framing = (f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                       f"crop={width}:{height}:{x}:(ih-oh)/2,setsar=1")
        # Normalize display pixels before fitting. Otherwise an anamorphic source
        # acquires bars or gets stretched when the final setsar=1 is applied.
        return "scale=trunc(iw*sar/2)*2:ih,setsar=1," + framing, width, height

    def preview(self, path: Path, directory: Path, plan: dict) -> list[dict]:
        info, digest = self._plan(path, plan)
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        result = []
        for clip_index, clip in enumerate(plan["clips"], 1):
            for profile_index, profile in enumerate(plan["outputs"], 1):
                framing, width, height = self._framing(info, profile)
                output = directory / f"{clip_index:03d}-{profile_index:03d}-{clip['id']}-{profile['name']}-preview.png"
                at = (clip["start"] + clip["end"]) / 2
                self._run([self.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", str(at),
                           *_LOCAL_INPUT, "-i", str(Path(path).resolve()), "-frames:v", "1", "-vf", framing, "-update", "1", str(output)], directory, "preview")
                result.append({"path": str(output), "profile": profile["name"], "clip": clip["id"], "width": width, "height": height})
        if _sha256(path) != digest:
            raise MediaError("Source changed during preview")
        return result

    def render(self, path: Path, directory: Path, plan: dict, segments: list, progress=None) -> dict:
        path = Path(path).resolve(strict=True)
        info, digest = self._plan(path, plan)
        directory = Path(directory).resolve()
        captions = plan.get("captions", {})
        mode = captions.get("mode", "none")
        cues = captions["cues"] if "cues" in captions else segments
        # Inspect every clip before any output is written, including when called
        # directly or with a snapshot approved by an older engine version.
        require_caption_boundaries(plan, cues=cues)
        directory.mkdir(parents=True, exist_ok=True)
        speed = float(plan.get("playback_speed", 1))
        delivery = plan.get("delivery", "clean")
        kinds = ["clean", "finished"] if delivery == "both" else [delivery]
        preset, crf = {"fast": ("ultrafast", "23"), "balanced": ("medium", "20"), "quality": ("slow", "18")}[plan.get("quality", "balanced")]
        total = len(plan["clips"]) * len(plan["outputs"]) * len(kinds)
        done, outputs, checks, warnings = 0, [], [], []
        if progress:
            progress(0.0, "Preparing approved media outputs")
        for clip_index, clip in enumerate(plan["clips"], 1):
            mapped = remap_cues(cues, clip["start"], clip["end"], speed) if mode != "none" else {"cues": [], "warnings": []}
            warnings.extend({**warning, "clip": clip["id"]} for warning in mapped["warnings"])
            expected_duration = (clip["end"] - clip["start"]) / speed
            for profile_index, profile in enumerate(plan["outputs"], 1):
                framing, width, height = self._framing(info, profile)
                base = f"{clip_index:03d}-{profile_index:03d}-{clip['id']}-{profile['name']}"
                if mode != "none":
                    srt = directory / f"{base}.srt"
                    write_srt(srt, mapped["cues"])
                    outputs.append({"path": str(srt), "name": srt.name, "kind": "sidecar", "sha256": _sha256(srt), "probe": None})
                for kind in kinds:
                    output = directory / f"{base}-{kind}.mp4"
                    if output == path:
                        raise MediaError("Output cannot overwrite the source")
                    filters = f"trim=duration={clip['end'] - clip['start']:.9f},setpts=(PTS-STARTPTS)/{speed:.9f},{framing}"
                    if kind == "finished" and mode == "burn" and mapped["cues"]:
                        fonts = directory / "fonts"
                        bundled = Path(__file__).parent / "assets" / "fonts"
                        font_paths = list(bundled.glob("*.ttf"))
                        if font_paths:
                            fonts.mkdir(exist_ok=True)
                            for font_path in font_paths:
                                shutil.copyfile(font_path, fonts / font_path.name)
                        ass = directory / f"{base}.ass"
                        write_ass(ass, mapped["cues"], width, height, "Inter" if font_paths else "Arial")
                        # Both relative paths are engine-generated safe identifiers. Neither
                        # caption text nor user filesystem paths enter the filter language.
                        filters += f",subtitles=filename={ass.name}"
                        if font_paths:
                            filters += ":fontsdir=fonts"
                    command = [self.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", str(clip["start"]),
                               *_LOCAL_INPUT, "-i", str(path), "-map", "0:v:0", "-vf", filters, "-c:v", "libx264", "-preset", preset,
                               "-crf", crf, "-pix_fmt", "yuv420p"]
                    if info["has_audio"]:
                        command += ["-map", "0:a:0", "-af", f"atrim=duration={clip['end'] - clip['start']:.9f},asetpts=PTS-STARTPTS,atempo={speed:.9f}",
                                    "-c:a", "aac", "-b:a", "192k"]
                    else:
                        command += ["-an"]
                    command += ["-t", f"{expected_duration:.9f}", "-sn", "-dn", "-map_metadata", "-1", "-movflags", "+faststart", str(output)]
                    self._run(command, directory, "render")
                    probe = self.inspect(output)
                    tolerance = max(0.12, expected_duration * 0.001)
                    valid = (probe["video_codec"] == "h264" and probe["pixel_format"] == "yuv420p"
                             and (probe["width"], probe["height"]) == (width, height)
                             and probe["sample_aspect_ratio"] == "1:1" and probe["has_audio"] == info["has_audio"]
                             and (not info["has_audio"] or probe["audio_codec"] == "aac")
                             and abs(probe["duration"] - expected_duration) <= tolerance)
                    check = {"name": output.name, "ok": valid, "expected_duration": expected_duration,
                             "actual_duration": probe["duration"], "width": width, "height": height}
                    checks.append(check)
                    if not valid:
                        raise MediaError(f"Rendered output failed codec/dimensions/audio/duration verification: {output.name}")
                    outputs.append({"path": str(output), "name": output.name, "kind": kind, "sha256": _sha256(output), "probe": probe})
                    done += 1
                    if progress:
                        progress(done / total, f"Verified {output.name}")
        if _sha256(path) != digest:
            raise MediaError("Source changed during rendering")
        return {"outputs": outputs, "verification": {"ok": True, "source_sha256": digest, "checks": checks}, "warnings": warnings}
