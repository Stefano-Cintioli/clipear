#!/usr/bin/env bash
# clipear — one-time setup: build whisper.cpp with Metal + download large-v3-turbo.
# macOS on Apple Silicon. Requires: git, cmake, ffmpeg (brew install cmake ffmpeg).
# Idempotent-ish: skips the clone/build/model steps that are already done.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WC="$REPO/whisper.cpp"
MODEL="ggml-large-v3-turbo.bin"

command -v cmake >/dev/null || { echo "ERR: cmake missing — run: brew install cmake"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ERR: ffmpeg missing — run: brew install ffmpeg"; exit 1; }

if [ ! -d "$WC" ]; then
  echo "cloning whisper.cpp ..."
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WC"
fi

if [ ! -x "$WC/build/bin/whisper-cli" ]; then
  echo "building whisper.cpp with Metal ..."
  cmake -S "$WC" -B "$WC/build" -DGGML_METAL=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build "$WC/build" -j --config Release
fi

if [ ! -f "$WC/models/$MODEL" ]; then
  echo "downloading model large-v3-turbo (~1.5 GB) ..."
  ( cd "$WC" && bash ./models/download-ggml-model.sh large-v3-turbo )
fi

echo ""
echo "=== VERIFY ==="
"$WC/build/bin/whisper-cli" -m "$WC/models/$MODEL" -f "$WC/samples/jfk.wav" -l auto 2>&1 \
  | grep -iE "metal|MTL|GPU name" | head -5 || true
echo ""
echo "setup done: binary $WC/build/bin/whisper-cli, model $WC/models/$MODEL"
