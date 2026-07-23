#!/usr/bin/env bash
# clipear — one-time setup. Idempotent (safe to re-run), user-space, no sudo.
# macOS on Apple Silicon only in v1.
#
# Exit codes the setup skill reacts to:
#   10 = unsupported OS/arch   11 = Homebrew missing (user must install it)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WC="$REPO/whisper.cpp"
MODEL_NAME="ggml-large-v3-turbo.bin"
MODEL="$WC/models/$MODEL_NAME"

# 1) OS / arch guard
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "clipear v1 supports macOS on Apple Silicon only."
  echo "Detected: $(uname -s) $(uname -m). Windows / Linux / Intel are not supported yet — contributions welcome."
  exit 10
fi
echo "ok: macOS Apple Silicon"

# 2) Homebrew must exist — never install it silently
if ! command -v brew >/dev/null 2>&1; then
  echo ""
  echo "Homebrew is not installed, and clipear will NOT install it for you."
  echo "Run the official installer yourself, then re-run this setup:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 11
fi
echo "ok: Homebrew present"

# 3) CLI deps (idempotent — brew is a no-op if already installed)
for f in ffmpeg yt-dlp cmake; do
  if brew list --versions "$f" >/dev/null 2>&1; then echo "ok: $f already installed"
  else echo "installing $f ..."; brew install "$f"; fi
done

# 4) whisper.cpp with Metal (idempotent)
if [ ! -d "$WC" ]; then
  echo "cloning whisper.cpp ..."; git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WC"
else echo "ok: whisper.cpp already cloned"; fi
if [ ! -x "$WC/build/bin/whisper-cli" ]; then
  echo "building whisper.cpp with Metal ..."
  cmake -S "$WC" -B "$WC/build" -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build "$WC/build" -j --config Release
else echo "ok: whisper-cli already built"; fi

# 5) model (~1.6 GB, idempotent)
if [ ! -f "$MODEL" ]; then
  echo "downloading model large-v3-turbo (~1.6 GB) ..."
  ( cd "$WC" && bash ./models/download-ggml-model.sh large-v3-turbo )
else echo "ok: model already downloaded"; fi

# 6) verify: sample transcription must show timestamps AND Metal in the log
echo ""
echo "=== VERIFY (sample transcription) ==="
"$WC/build/bin/whisper-cli" -m "$MODEL" -f "$WC/samples/jfk.wav" -l en 2>&1 \
  | grep -iE "GPU name|using .*Metal|Metal backend|-->" | head -6
echo ""
echo "setup complete. whisper-cli: $WC/build/bin/whisper-cli"
