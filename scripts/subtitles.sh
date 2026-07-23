#!/usr/bin/env bash
# clipear — subtitle generation (SRT sidecar only, no burn-in)
# Usage: scripts/subtitles.sh <slug> [--lang <code>]   (run ingest first)
#
# Re-transcribes into short, sentence-level cues suitable for video editors
# (CapCut, Premiere, etc.). Output is a plain .srt you import and style yourself.
# Language auto-detects unless --lang is given. The domain glossary is applied so
# proper nouns are spelled correctly.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER="$REPO/whisper.cpp/build/bin/whisper-cli"
MODEL="$REPO/whisper.cpp/models/ggml-large-v3-turbo.bin"
WORK_DIR="$REPO/work"

SLUG="${1:?usage: subtitles.sh <slug> [--lang <code>]}"; shift || true
LANG="auto"
if [ "${1:-}" = "--lang" ]; then LANG="${2:?--lang needs a code, e.g. en}"; fi

WAV="$WORK_DIR/$SLUG.wav"
[ -f "$WAV" ] || { echo "ERR: wav not found: $WAV (run ingest first)"; exit 1; }

# domain glossary -> whisper prompt (comment lines and blanks stripped)
GLOSSARY_FILE="$REPO/prompts/whisper-glossary.txt"
PROMPT=""
[ -f "$GLOSSARY_FILE" ] && PROMPT="$(grep -vE '^\s*#|^\s*$' "$GLOSSARY_FILE" | tr '\n' ' ' | sed 's/ *$//')"

OUTPUT_DIR="${OUTPUT_DIR:-$HOME/clipear-output}"
DEST="$OUTPUT_DIR/$SLUG"; mkdir -p "$DEST"

# -ml 32 + -sow => short, one-line cues that read well and split on word boundaries
WHARGS=(-m "$MODEL" -f "$WAV" -l "$LANG" -osrt -ml 32 -sow -of "$DEST/$SLUG")
[ -n "$PROMPT" ] && WHARGS+=(--prompt "$PROMPT")

echo "generating subtitles (lang=$LANG) ..."
"$WHISPER" "${WHARGS[@]}" >/dev/null 2>&1

SRT="$DEST/$SLUG.srt"
[ -f "$SRT" ] || { echo "ERR: whisper did not produce $SRT"; exit 2; }

CUES=$(grep -cE '^[0-9]+$' "$SRT")
echo ""
echo "=== SRT SIDECAR ==="
echo "file : $SRT"
echo "cues : $CUES"
echo "--- first 6 lines ---"; head -6 "$SRT"
echo ""
echo "Next (optional, agent-driven, no API):"
echo "  - Fix any mis-transcribed proper nouns against the glossary (change nothing else)."
echo "  - Translate: produce <slug>.<lang>.srt, keeping every timestamp block identical."
