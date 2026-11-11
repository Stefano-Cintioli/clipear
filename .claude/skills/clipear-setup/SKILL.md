---
name: clipear-setup
description: Guide a user through clipear's Python, FFmpeg, whisper.cpp/model, and optional MCP setup on macOS, Windows, or Linux, verifying the actual installed capabilities. Use for setup or missing dependency diagnosis.
disable-model-invocation: true
---

# clipear setup

Read repository-root [AGENTS.md](../../../AGENTS.md) and follow
[docs/setup.md](../../../docs/setup.md), using the section for the user's host and
shell. Explain each dependency before installing it and respect existing scope.
Use a project virtual environment; do not change global agent settings or copy
skills globally unless requested.

Run `doctor`, report what actually works, then verify a small real transcription
and media export if the required executable/model are available. Missing tools
are not a passed setup. Do not imply a native app connection was tested merely
because an MCP server started.

`scripts/setup.sh` is the optional legacy Apple Silicon setup, not the portable
installer. It requires Homebrew, builds whisper.cpp with Metal, and downloads a
large model. It exits 10 on an unsupported OS/architecture or 11 when Homebrew is
missing. Never run it as a fallback on Windows, Linux, or Intel Mac, and never
install Homebrew silently.
