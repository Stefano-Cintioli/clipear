---
name: clipear-setup
description: One-time, self-driving setup for clipear on macOS Apple Silicon. Installs ffmpeg/yt-dlp/cmake via Homebrew, builds whisper.cpp with Metal, downloads the large-v3-turbo model, verifies with a sample transcription, and offers to install the clipear skill globally. Idempotent and user-space (no sudo). Manual trigger only.
disable-model-invocation: true
---

# clipear setup

Drives `scripts/setup.sh` and handles the two points where a human decision is needed.
Everything stays on the user's machine. Never install Homebrew for them.

## Steps

1. **Run** `scripts/setup.sh` and stream its output to the user.

2. **If it exits `10` (unsupported OS/arch):** tell the user clipear v1 supports
   **macOS on Apple Silicon only**, relay what was detected, and stop. Do not attempt
   workarounds.

3. **If it exits `11` (Homebrew missing):** show the official Homebrew install command
   from the output, tell the user to run it themselves in their terminal, and **wait**.
   Never run the Homebrew installer yourself. Once they confirm it's installed, re-run
   `scripts/setup.sh` (it's idempotent, so completed steps are skipped).

4. **On success:** show the verification block — the sample transcription must display
   both timestamps (`-->` lines) and Metal in the log (`GPU name` / `Metal backend`).
   If Metal is absent, say so; the build fell back to CPU and should be rebuilt.

5. **Offer global install:** ask whether they want `/clipear` available from any folder.
   If yes, run:
   ```
   mkdir -p ~/.claude/skills && cp -r .claude/skills/clipear ~/.claude/skills/clipear
   ```
   (project-scoped copy stays in the repo either way). Then tell them to reload skills.

## Notes
- `setup.sh` is idempotent: re-running skips anything already done. Safe after a partial run.
- No `sudo` anywhere. The model download is ~1.6 GB.
- v1 produces SRT sidecar subtitles, so **libass is not required** — plain ffmpeg is enough.
