#!/usr/bin/env bash
# clipear — Stage 2: ingest (acquire + audio-extract)
# Usage: scripts/ingest.sh <youtube-url | x-url | local-file-path> [slug-override]
#
# - YouTube / X / other yt-dlp sites: download h264/mp4 ONLY (stream-copy safe).
#   If no h264 stream exists, STOP and show options — never grab webm.
# - Local file: skip download, use as-is.
# - Always extract a 16 kHz mono WAV for whisper.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DL_DIR="$REPO/downloads"
WORK_DIR="$REPO/work"
mkdir -p "$DL_DIR" "$WORK_DIR"

INPUT="${1:?usage: ingest.sh <url|file> [slug]}"
SLUG_OVERRIDE="${2:-}"

# h264/mp4-only selector: video=avc1 mp4, audio=m4a; progressive h264 mp4 fallback.
# Deliberately NO webm/vp9/av1 fallback — we'd rather stop than ship a webm master.
FMT='bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4][vcodec^=avc1]'

# YouTube's default player client (android_vr) 403s on media and other clients
# expose only partial h264 catalogs; tv_embedded lists the full h264 set AND its
# URLs download. Pinned so probe + download see the same formats. (Ignored by non-YT.)
YT_ARGS=(--extractor-args "youtube:player_client=tv_embedded")

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-60
}

classify() {
  case "$1" in
    *youtube.com/*|*youtu.be/*) echo youtube ;;
    *x.com/*|*twitter.com/*)    echo x ;;
    http://*|https://*)         echo url ;;
    *) if [ -f "$1" ]; then echo local; else
         echo "ERR: not a URL and file does not exist: $1" >&2; exit 1
       fi ;;
  esac
}

KIND="$(classify "$INPUT")"
echo "input type : $KIND"

VIDEO=""
if [ "$KIND" = "local" ]; then
  VIDEO="$INPUT"
  if [ -n "$SLUG_OVERRIDE" ]; then SLUG="$SLUG_OVERRIDE"
  else SLUG="$(slugify "$(basename "${INPUT%.*}")")"; fi
  echo "slug       : $SLUG"
  echo "source     : local file (no download)"
else
  echo "probing formats ..."
  INFO="$WORK_DIR/.ingest-info.json"
  yt-dlp "${YT_ARGS[@]}" -j --no-warnings "$INPUT" > "$INFO"

  TITLE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["title"])' "$INFO")"
  if [ -n "$SLUG_OVERRIDE" ]; then SLUG="$SLUG_OVERRIDE"; else SLUG="$(slugify "$TITLE")"; fi
  echo "title      : $TITLE"
  echo "slug       : $SLUG"

  # Decide: is h264/mp4 available? note if a higher-res exists only in another codec.
  DECISION="$(python3 - "$INFO" <<'PY'
import json, sys
f = json.load(open(sys.argv[1]))
vids = [x for x in f.get("formats", []) if x.get("vcodec") and x["vcodec"] != "none" and x.get("height")]
h264 = [x for x in vids if str(x.get("vcodec","")).startswith("avc1")]
h264_max = max((x["height"] for x in h264), default=0)
if vids:
    top = max(vids, key=lambda x: x["height"])
    any_max, any_codec = top["height"], str(top.get("vcodec","")).split(".")[0]
else:
    any_max, any_codec = 0, "none"
if not h264:
    print(f"STOP\t{any_max}\t{any_codec}")
else:
    print(f"OK\t{h264_max}\t{any_max}\t{any_codec}")
PY
)"

  if [ "${DECISION%%$'\t'*}" = "STOP" ]; then
    ANY_MAX="$(echo "$DECISION" | cut -f2)"; ANY_CODEC="$(echo "$DECISION" | cut -f3)"
    echo ""
    echo "STOP: no h264/mp4 stream available. Highest available is ${ANY_MAX}p in ${ANY_CODEC}."
    echo "Won't silently download webm/vp9/av1 (breaks stream copy)."
    echo "Full format list:"
    yt-dlp "${YT_ARGS[@]}" -F --no-warnings "$INPUT"
    echo ""
    echo "Options:"
    echo "  a) re-run picking a specific h264 format id (edit FMT)"
    echo "  b) allow ${ANY_CODEC} download + one-time re-encode to h264 (tell me)"
    echo "  c) accept a lower-res h264 if one exists above"
    exit 2
  fi

  H264_MAX="$(echo "$DECISION" | cut -f2)"; ANY_MAX="$(echo "$DECISION" | cut -f3)"; ANY_CODEC="$(echo "$DECISION" | cut -f4)"
  echo "h264 max   : ${H264_MAX}p   (overall max ${ANY_MAX}p ${ANY_CODEC})"

  VIDEO="$DL_DIR/$SLUG.mp4"
  echo "downloading (h264/mp4 only) -> $VIDEO"
  yt-dlp "${YT_ARGS[@]}" -f "$FMT" --merge-output-format mp4 --no-progress -o "$DL_DIR/$SLUG.%(ext)s" --no-warnings "$INPUT"

  # Resolution-vs-compatibility tradeoff report (after download).
  # h264 stays the default; this just makes the tradeoff visible when it happens.
  if [ "$ANY_MAX" -gt "$H264_MAX" ]; then
    echo ""
    echo "WARNING: traded resolution for h264 compatibility."
    echo "  downloaded : ${H264_MAX}p h264"
    echo "  available  : ${ANY_MAX}p ${ANY_CODEC} (not h264 — skipped)"
    echo "  available formats:"
    yt-dlp "${YT_ARGS[@]}" -F --no-warnings "$INPUT" 2>/dev/null | sed 's/^/    /'
  else
    echo "tradeoff   : none — ${H264_MAX}p h264 is the highest resolution available."
  fi
fi

# --- codec guard (also protects against av1-in-mp4 slipping through) ---
VCODEC="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$VIDEO")"
if [ "$KIND" != "local" ] && [ "$VCODEC" != "h264" ]; then
  echo "STOP: downloaded video codec is '$VCODEC', not h264 — not stream-copy safe."; exit 3
fi

# --- audio extract: 16 kHz mono WAV for whisper ---
WAV="$WORK_DIR/$SLUG.wav"
echo "extracting audio -> $WAV (16 kHz mono)"
ffmpeg -y -loglevel error -i "$VIDEO" -vn -ac 1 -ar 16000 "$WAV"

# --- evidence ---
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
VDUR="$(dur "$VIDEO")"; ADUR="$(dur "$WAV")"
echo ""
echo "=== SOURCE VIDEO ($VIDEO) ==="
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -show_entries format=format_name,duration -of default=noprint_wrappers=1 "$VIDEO"
echo "=== AUDIO WAV ($WAV) ==="
ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,sample_rate,channels \
  -show_entries format=duration -of default=noprint_wrappers=1 "$WAV"
echo "=== DURATION MATCH ==="
python3 -c "v=$VDUR; a=$ADUR; d=abs(v-a); print(f'video={v:.2f}s  wav={a:.2f}s  delta={d:.2f}s  -> {\"OK\" if d<1.0 else \"MISMATCH\"}')"

echo ""
echo "ingest done: SLUG=$SLUG"
echo "  video: $VIDEO"
echo "  wav  : $WAV"
