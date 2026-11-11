"""Host-controlled settings. MCP callers cannot change these values."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "clipear"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "clipear"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "clipear"


@dataclass(frozen=True)
class Settings:
    home: Path = field(default_factory=default_home)
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    yt_dlp: str = "yt-dlp"
    whisper_cli: str | None = None
    whisper_model: Path | None = None
    input_roots: tuple[Path, ...] = field(default_factory=lambda: (Path.cwd(),))

    @classmethod
    def from_env(cls, home: str | Path | None = None) -> "Settings":
        roots = os.environ.get("CLIPEAR_INPUT_ROOTS")
        model = os.environ.get("CLIPEAR_MODEL")
        return cls(
            home=Path(home or os.environ.get("CLIPEAR_HOME") or default_home()).expanduser().resolve(),
            ffmpeg=os.environ.get("CLIPEAR_FFMPEG", "ffmpeg"),
            ffprobe=os.environ.get("CLIPEAR_FFPROBE", "ffprobe"),
            yt_dlp=os.environ.get("CLIPEAR_YT_DLP", shutil.which("yt-dlp") or "yt-dlp"),
            whisper_cli=os.environ.get("CLIPEAR_WHISPER") or shutil.which("whisper-cli"),
            whisper_model=Path(model).expanduser().resolve() if model else None,
            input_roots=tuple(Path(p).expanduser().resolve() for p in roots.split(os.pathsep) if p) if roots else (Path.cwd().resolve(),),
        )

    def worker_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"CLIPEAR_HOME": str(self.home), "CLIPEAR_FFMPEG": self.ffmpeg,
                    "CLIPEAR_FFPROBE": self.ffprobe, "CLIPEAR_YT_DLP": self.yt_dlp,
                    "CLIPEAR_INPUT_ROOTS": os.pathsep.join(str(p) for p in self.input_roots)})
        if self.whisper_cli:
            env["CLIPEAR_WHISPER"] = self.whisper_cli
        if self.whisper_model:
            env["CLIPEAR_MODEL"] = str(self.whisper_model)
        # The media worker does not need an MCP transport credential.
        env.pop("CLIPEAR_HTTP_TOKEN", None)
        return env
