"""One workflow shared by human CLI and model-facing MCP tools."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .captions import caption_warnings
from .store import Store, pack


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def safe_name(value, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", value):
        raise ValueError(f"{name} must contain only letters, numbers, - and _ (max 48)")
    return value


class Service:
    def __init__(self, settings: Settings, *, media=None, start_workers: bool = True):
        self.settings = settings
        self.store = Store(settings.home)
        self.media = media
        self.start_workers = start_workers

    def _media(self):
        if self.media is None:
            from .media import Media
            self.media = Media(self.settings)
        return self.media

    def check_setup(self) -> dict:
        tools = {}
        for name in ("ffmpeg", "ffprobe", "yt_dlp", "whisper_cli"):
            command = getattr(self.settings, name)
            path = shutil.which(command) if command else None
            if not path and command and Path(command).is_file():
                path = str(Path(command).resolve())
            tools[name] = {"available": bool(path), "path": path}
        if not tools["yt_dlp"]["available"]:
            import importlib.util
            tools["yt_dlp"]["available"] = importlib.util.find_spec("yt_dlp") is not None
            tools["yt_dlp"]["module"] = tools["yt_dlp"]["available"]
        model = self.settings.whisper_model
        tools["whisper_model"] = {"available": bool(model and model.is_file()), "path": str(model) if model else None}
        capabilities = {"ass_captions": False, "software_h264": False}
        if tools["ffmpeg"]["available"]:
            for flag, key, needle in [("-filters", "ass_captions", " ass "), ("-encoders", "software_h264", "libx264")]:
                try:
                    result = subprocess.run([self.settings.ffmpeg, "-hide_banner", flag], capture_output=True, text=True, timeout=15)
                    capabilities[key] = result.returncode == 0 and needle in result.stdout
                except (OSError, subprocess.TimeoutExpired):
                    pass
        return {"version": "0.2.0", "platform": sys.platform, "home": str(self.settings.home),
                "mcp_command": [sys.executable, "-m", "clipear", "mcp"],
                "input_roots": [str(p) for p in self.settings.input_roots], "tools": tools, "capabilities": capabilities,
                "media_ready": tools["ffmpeg"]["available"] and tools["ffprobe"]["available"] and capabilities["software_h264"],
                "transcription_ready": all(tools[k]["available"] for k in ("ffmpeg", "ffprobe", "whisper_cli", "whisper_model")),
                "privacy": "Transcription/rendering run on this host. Transcript text supplied to a connected cloud agent is sent to that agent's provider."}

    def _validate_input(self, source: str) -> str:
        if not isinstance(source, str) or not source or "\x00" in source:
            raise ValueError("Provide a YouTube HTTPS URL or camera file")
        if source.startswith(("http:", "https:")):
            url = urlsplit(source)
            if url.scheme != "https" or url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"} or url.username or url.password or url.port not in (None, 443):
                raise ValueError("Only public YouTube HTTPS video URLs are supported")
            return source
        if source.startswith("-"):
            raise ValueError("Source cannot be a command option")
        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("Source must be a regular file")
        if not any(path.is_relative_to(Path(root).expanduser().resolve()) for root in self.settings.input_roots):
            raise PermissionError("File is outside host-configured CLIPEAR_INPUT_ROOTS")
        return str(path)

    def _queue(self, kind: str, request: dict) -> dict:
        return self._launch(self.store.new_job(kind, request))

    def _launch(self, job_id: str) -> dict:
        if self.start_workers:
            directory = self.settings.home / "jobs" / job_id
            directory.mkdir(parents=True, exist_ok=True)
            kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
            try:
                with (directory / "worker.log").open("ab") as log:
                    process = subprocess.Popen([sys.executable, "-m", "clipear.worker", "--home", str(self.settings.home), job_id], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=self.settings.worker_env(), close_fds=True, **kwargs)
                # Reap children while this host lives; the detached worker still
                # survives this daemon waiter and its parent process exiting.
                def observe_exit():
                    returncode = process.wait()
                    self.store.worker_exited(job_id, returncode, directory / "worker.log")
                threading.Thread(target=observe_exit, daemon=True).start()
            except OSError as error:
                self.store.finish_job(job_id, error=f"Could not start worker: {error}")
        return {"job_id": job_id, "status": self.store.get_job(job_id)["status"]}

    def import_source(self, source: str) -> dict:
        return self._queue("import", {"source": self._validate_input(source), "source_id": uuid.uuid4().hex})

    def _verified_source(self, source_id: str) -> dict:
        source = self.store.get_source(source_id)
        path = Path(source["path"]).resolve()
        expected_dir = (self.settings.home / "sources" / source_id).resolve()
        if not path.is_relative_to(expected_dir) or not path.is_file():
            raise PermissionError("Stored source is missing or outside its workspace")
        if file_hash(path) != source["sha256"]:
            raise PermissionError("Source bytes changed; import again and approve a new plan")
        return source

    def transcribe_source(self, source_id: str, language: str = "auto", glossary: str = "") -> dict:
        self._verified_source(source_id)
        if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2,3}(?:-[A-Za-z]{2,8})?", language):
            raise ValueError("Invalid transcription language")
        if not isinstance(glossary, str) or len(glossary) > 8000:
            raise ValueError("Glossary must be text up to 8000 characters")
        return self._queue("transcribe", {"source_id": source_id, "language": language, "glossary": glossary})

    def get_transcript(self, source_id: str, offset: int = 0, limit: int = 200) -> dict:
        if isinstance(offset, bool) or isinstance(limit, bool) or not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 200:
            raise ValueError("Transcript paging requires offset >= 0 and limit 1..200")
        source = self.store.get_source(source_id)
        transcript = source["transcript"]
        if transcript is None:
            raise ValueError("No transcript yet; transcribe this source and check its job")
        segments = transcript["segments"]
        return {"source_id": source_id, "language": transcript.get("language", "auto"), "segments": segments[offset:offset+limit], "offset": offset, "total": len(segments), "next_offset": offset+limit if offset+limit < len(segments) else None}

    def create_edit_plan(self, source_id: str, clips: list[dict], brief: dict | None = None, outputs: list[dict] | None = None, captions: dict | None = None, delivery: str = "clean", playback_speed: float = 1.0, quality: str = "balanced", plan_id: str | None = None) -> dict:
        source = self._verified_source(source_id)
        duration = number(source["info"]["duration"], "Source duration")
        if not isinstance(clips, list) or not 1 <= len(clips) <= 100:
            raise ValueError("Provide 1..100 selected clips")
        selected, seen = [], set()
        for i, clip in enumerate(clips):
            if not isinstance(clip, dict):
                raise ValueError("Each clip must be an object")
            cid = safe_name(clip.get("id", f"c{i+1}"), "Clip ID")
            if cid.casefold() in seen:
                raise ValueError("Clip IDs must be unique ignoring case")
            seen.add(cid.casefold())
            start, end = number(clip.get("start"), "Clip start"), number(clip.get("end"), "Clip end")
            if not 0 <= start < end <= duration:
                raise ValueError("Clip must be inside the source duration with start < end")
            title = clip.get("title", cid)
            if not isinstance(title, str) or len(title) > 300:
                raise ValueError("Clip title must be text up to 300 characters")
            selected.append({"id": cid, "title": title, "start": start, "end": end})
        if brief is None:
            brief = {}
        if not isinstance(brief, dict) or len(pack(brief)) > 64000:
            raise ValueError("Brief must be a JSON object up to 64000 characters")
        if brief.get("privacy_mode", "local") not in {"local", "cloud"}:
            raise ValueError("privacy_mode must be local or cloud; it labels the processing host, not LLM privacy")
        if outputs is None:
            outputs = [{"name": "source", "ratio": "source"}]
        if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
            raise ValueError("Provide 1..8 output profiles")
        profiles, names = [], set()
        for output in outputs:
            if not isinstance(output, dict):
                raise ValueError("Output profiles must be objects")
            ratio = output.get("ratio", "source")
            if ratio not in {"source", "16:9", "9:16", "1:1", "4:5"}:
                raise ValueError("Unsupported aspect ratio")
            name = safe_name(output.get("name", ratio.replace(":", "x")), "Output name")
            if name.casefold() in names:
                raise ValueError("Output names must be unique ignoring case")
            names.add(name.casefold())
            height = output.get("height", {"source": source["info"]["height"], "9:16": 1920, "4:5": 1350}.get(ratio, 1080))
            if isinstance(height, bool) or not isinstance(height, int) or not 64 <= height <= 4320 or height % 2:
                raise ValueError("Output height must be an even integer 64..4320")
            fit, position = output.get("fit", "pad"), output.get("position", "center")
            if fit not in {"pad", "crop"} or position not in {"left", "center", "right"}:
                raise ValueError("Use pad/crop and left/center/right framing")
            profiles.append({"name": name, "ratio": ratio, "height": height, "fit": fit, "position": position})
        speed = number(playback_speed, "Playback speed")
        if not .5 <= speed <= 2:
            raise ValueError("Playback speed must be 0.5..2")
        if quality not in {"fast", "balanced", "quality"} or delivery not in {"clean", "finished", "both"}:
            raise ValueError("Unsupported quality or delivery mode")
        if captions is None:
            captions = {"mode": "none"}
        if not isinstance(captions, dict) or captions.get("mode", "none") not in {"none", "sidecar", "burn"}:
            raise ValueError("Caption mode must be none, sidecar or burn")
        mode = captions.get("mode", "none")
        if mode == "burn" and delivery == "clean":
            raise ValueError("Burned captions require delivery finished or both; clean clips never contain burned text")
        cues = captions.get("cues")
        if cues is None:
            cues = (source["transcript"] or {}).get("segments", []) if mode != "none" else []
        if not isinstance(cues, list) or len(cues) > 20000:
            raise ValueError("Captions require a list of up to 20000 source-timeline cues")
        clean_cues = []
        for cue in cues:
            if not isinstance(cue, dict):
                raise ValueError("Each caption cue must be an object")
            start, end = number(cue.get("start"), "Cue start"), number(cue.get("end"), "Cue end")
            text = cue.get("text")
            if not 0 <= start < end <= duration or not isinstance(text, str) or not text.strip() or len(text) > 8000 or "\x00" in text:
                raise ValueError("Invalid caption cue range or text")
            clean_cues.append({"start": start, "end": end, "text": text})
        language = captions.get("language", (source["transcript"] or {}).get("language", "auto"))
        if not isinstance(language, str) or len(language) > 40:
            raise ValueError("Caption language must be short text")
        document = {"version": 1, "source_id": source_id, "source_sha256": source["sha256"], "brief": brief, "clips": selected, "outputs": profiles, "captions": {"mode": mode, "language": language, "cues": clean_cues}, "delivery": delivery, "playback_speed": speed, "quality": quality}
        digest = hashlib.sha256(pack(document).encode("utf-8")).hexdigest()
        plan = self.store.save_plan(source_id, document, digest, plan_id)
        return self._plan_result(plan)

    def _plan_result(self, plan: dict) -> dict:
        plan["warnings"] = caption_warnings(plan["document"])
        plan["approval_instructions"] = {"message": "A person must review this exact plan through the separate CLI/browser. MCP has no approval tool.", "command": ["clipear", "--home", str(self.settings.home), "review", plan["id"]]}
        return plan

    def get_edit_plan(self, plan_id: str) -> dict:
        return self._plan_result(self.store.get_plan(plan_id))

    def preview_edit_plan(self, plan_id: str) -> dict:
        plan = self.store.get_plan(plan_id)
        source = self._verified_source(plan["source_id"])
        return self._queue("preview", {"plan": plan["document"], "digest": plan["digest"], "source": source})

    def render_approved_plan(self, plan_id: str) -> dict:
        plan = self.store.get_plan(plan_id)
        source = self._verified_source(plan["source_id"])
        return self._launch(self.store.queue_render(plan_id, source))

    def get_job(self, job_id: str) -> dict:
        return self.store.get_job(job_id)

    def run_job(self, job_id: str):
        if not self.store.claim_job(job_id):
            return
        request = self.store.job_request(job_id)
        kind = self.store.get_job(job_id)["kind"]
        directory = self.settings.home / "jobs" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        progress = lambda fraction, message: self.store.progress(job_id, fraction, message)
        try:
            progress(.02, f"Starting {kind}")
            media = self._media()
            if kind == "import":
                source_id = request["source_id"]
                # Recheck the allowed root in the detached processing host too.
                locator = self._validate_input(request["source"])
                result = media.ingest(locator, self.settings.home / "sources" / source_id)
                self.store.add_source(source_id, locator, str(result["path"]), result["sha256"], result["info"])
                result = {**result, "source_id": source_id}
            elif kind == "transcribe":
                source = self._verified_source(request["source_id"])
                progress(.1, "Transcribing on the processing host")
                result = media.transcribe(Path(source["path"]), directory, request["language"], request["glossary"])
                self.store.set_transcript(source["id"], result)
                result = {"source_id": source["id"], "language": result["language"], "segments": len(result["segments"]), "transcript_ready": True}
            elif kind in {"preview", "render"}:
                plan = request["plan"]
                source = self._verified_source(plan["source_id"])
                if source["sha256"] != plan["source_sha256"]:
                    raise PermissionError("Source fingerprint differs from approved plan")
                if kind == "preview":
                    result = {"previews": media.preview(Path(source["path"]), directory, plan), "digest": request["digest"]}
                else:
                    # Plan document is the frozen, atomically authorized job snapshot.
                    if hashlib.sha256(pack(plan).encode("utf-8")).hexdigest() != request["digest"]:
                        raise PermissionError("Render snapshot digest mismatch")
                    segments = (source["transcript"] or {}).get("segments", [])
                    result = media.render(Path(source["path"]), directory, plan, segments, progress=progress)
                    result.update({"plan_id": request["plan_id"], "revision": request["revision"], "digest": request["digest"]})
            else:
                raise ValueError(f"Unsupported job kind: {kind}")
            self.store.finish_job(job_id, result=result)
        except Exception as error:
            self.store.finish_job(job_id, error=f"{type(error).__name__}: {error}")
