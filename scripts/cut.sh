#!/usr/bin/env bash
# clipear — Stage 5: cut & deliver (lossless stream copy, keyframe-padded)
# Usage: scripts/cut.sh <slug> <source-url> <picks-file>
#   picks-file: one clip per line — "topic-slug|start_sec|end_sec|compliance"
#   (compliance = "-" if none). Line order = clip order = NN.
#
# Output goes to $OUTPUT_DIR/<slug>/ (default ~/clipear-output). Set OUTPUT_DIR to
# your own path — e.g. a cloud-synced folder — in the environment.
#
# Each clip starts at the keyframe AT OR BEFORE the requested in-point (so no
# opening words are lost), then stream-copies to the requested out-point. No
# re-encode: output codec/resolution are identical to the master.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SLUG="${1:?usage: cut.sh <slug> <source-url> <picks-file>}"
SRC_URL="${2:?need source url}"
PICKS="${3:?need picks file}"

OUTPUT_DIR="${OUTPUT_DIR:-$HOME/clipear-output}"
MASTER="$REPO/downloads/$SLUG.mp4"
[ -f "$MASTER" ] || { echo "ERR: master not found: $MASTER"; exit 1; }
DEST="$OUTPUT_DIR/$SLUG"
mkdir -p "$DEST"
NOTE="$REPO/notes/$SLUG.md"; mkdir -p "$REPO/notes"
TODAY="$(date +%F)"

# master reference (for no-re-encode proof)
read -r M_VC M_W M_H < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height -of csv=p=0 "$MASTER" | tr ',' ' ')
echo "master: $M_VC ${M_W}x${M_H}  ($MASTER)"
echo "output: $DEST"
echo ""

hms() { python3 -c "s=$1;h=int(s//3600);m=int((s%3600)//60);x=s%60;print(f'{h:02d}:{m:02d}:{x:05.2f}')"; }

# find keyframe at/just-before a timestamp (scan a 30s window, decode keyframes only)
find_kf() {
  local start="$1" from
  from=$(python3 -c "print(max(0,$start-30))")
  ffprobe -v error -select_streams v:0 -skip_frame nokey \
    -show_entries frame=best_effort_timestamp_time -of csv=p=0 \
    -read_intervals "${from}%${start}" "$MASTER" 2>/dev/null \
    | awk 'NF && $1!="N/A"' \
    | awk -v s="$start" '($1+0)<=(s+0){last=$1} END{print (last==""?"NONE":last)}'
}

# notes header
{
  echo "# $SLUG — cut log"
  echo ""
  echo "- Source: $SRC_URL"
  echo "- Date: $TODAY"
  echo "- Master: $M_VC ${M_W}x${M_H}, lossless stream copy (\`-c copy\`), keyframe-padded start"
  echo "- Delivered to: \`$DEST/\`"
  echo ""
  echo "| # | file | requested | actual (after pad) | dur req→act | size | compliance |"
  echo "|---|------|-----------|--------------------|-------------|------|------------|"
} > "$NOTE"

echo "=== PER-CLIP EVIDENCE ==="
N=0
while IFS='|' read -r topic start end compliance; do
  [ -z "${topic:-}" ] && continue
  case "$topic" in \#*) continue;; esac
  N=$((N+1)); NN=$(printf "%02d" "$N")
  OUT="$DEST/clip_${NN}_${topic}.mp4"

  KF="$(find_kf "$start")"
  if [ "$KF" = "NONE" ]; then echo "  clip $NN: no keyframe found in window, using exact -ss (may show a brief artifact)"; KF="$start"; fi
  DUR=$(python3 -c "print(round($end-$KF,3))")

  ffmpeg -y -loglevel error -ss "$KF" -i "$MASTER" -t "$DUR" \
    -map 0:v:0 -map 0:a:0 -c copy -avoid_negative_ts make_zero -movflags +faststart "$OUT"

  # measure
  read -r C_VC C_W C_H < <(ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height -of csv=p=0 "$OUT" | tr ',' ' ')
  A_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
  A_DUR=$(python3 -c "print(round($A_DUR,2))")
  R_DUR=$(python3 -c "print(round($end-$start,2))")
  A_END=$(python3 -c "print(round($KF+$A_DUR,2))")
  PAD=$(python3 -c "print(round($start-$KF,2))")
  DELTA=$(python3 -c "print(round($A_DUR-$R_DUR,2))")
  SIZE=$(ls -lh "$OUT" | awk '{print $5}')
  SAME=$([ "$C_VC" = "$M_VC" ] && [ "$C_W" = "$M_W" ] && [ "$C_H" = "$M_H" ] && echo "IDENTICAL" || echo "DIFFERENT")

  printf "clip %s  %s\n" "$NN" "$(basename "$OUT")"
  printf "  codec/res : %s %sx%s vs master %s %sx%s  -> %s (no re-encode)\n" "$C_VC" "$C_W" "$C_H" "$M_VC" "$M_W" "$M_H" "$SAME"
  printf "  requested : %s-%s  (%.2fs)\n" "$(hms "$start")" "$(hms "$end")" "$R_DUR"
  printf "  actual    : %s-%s  (%.2fs)  [head pad +%ss]\n" "$(hms "$KF")" "$(hms "$A_END")" "$A_DUR" "$PAD"
  printf "  dur delta : req %.2fs -> act %.2fs  (delta +%ss = keyframe pad)\n" "$R_DUR" "$A_DUR" "$DELTA"
  printf "  size      : %s\n\n" "$SIZE"

  echo "| $NN | clip_${NN}_${topic}.mp4 | $(hms "$start")-$(hms "$end") | $(hms "$KF")-$(hms "$A_END") | ${R_DUR}s->${A_DUR}s | $SIZE | $compliance |" >> "$NOTE"
done < "$PICKS"

echo "wrote log: $NOTE"
echo ""
echo "=== OUTPUT FOLDER ==="
ls -lh "$DEST" | awk 'NR>1{print "  "$5"\t"$NF}'
