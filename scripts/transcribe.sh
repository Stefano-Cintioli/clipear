#!/usr/bin/env bash
# clipear — Stage 3: transcription (whisper.cpp large-v3-turbo, Metal)
# Usage: scripts/transcribe.sh <slug> [--prompt "domain glossary ..."]
#
# Produces:
#   downloads/<slug>.json          full word/token-level JSON (gitignored) — for cut refinement only
#   work/<slug>.segments.txt       compact "start | end | Speaker X | text" — the ONLY file analysis reads
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER="$REPO/whisper.cpp/build/bin/whisper-cli"
MODEL="$REPO/whisper.cpp/models/ggml-large-v3-turbo.bin"
SAMPLE="$REPO/whisper.cpp/samples/jfk.wav"
DL_DIR="$REPO/downloads"; WORK_DIR="$REPO/work"

SLUG="${1:?usage: transcribe.sh <slug> [--prompt \"glossary\"]}"; shift || true
# Default prompt = the stored domain glossary (brand/name spellings whisper gets
# wrong). An explicit --prompt overrides it.
GLOSSARY_FILE="$REPO/prompts/whisper-glossary.txt"
PROMPT=""
# strip comment lines (#...) and blanks; the rest is the whisper prompt
[ -f "$GLOSSARY_FILE" ] && PROMPT="$(grep -vE '^\s*#|^\s*$' "$GLOSSARY_FILE" | tr '\n' ' ' | sed 's/ *$//')"
if [ "${1:-}" = "--prompt" ]; then PROMPT="${2:?--prompt needs a value}"; fi

WAV="$WORK_DIR/$SLUG.wav"
[ -f "$WAV" ] || { echo "ERR: wav not found: $WAV (run ingest first)"; exit 1; }
JSON="$DL_DIR/$SLUG.json"
COMPACT="$WORK_DIR/$SLUG.segments.txt"
STDERR="$WORK_DIR/.whisper-$SLUG.stderr"

AUDIO_DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WAV")"

# Warm the run: compile Metal shaders + page-cache the 1.5 GB model on a tiny clip,
# so the measured wall clock reflects steady-state transcription, not one-time init.
echo "warming up (Metal shaders + model load) ..."
"$WHISPER" -m "$MODEL" -f "$SAMPLE" -l auto -nt >/dev/null 2>&1 || true

WHARGS=(-m "$MODEL" -f "$WAV" -l auto --output-json-full -of "$DL_DIR/$SLUG")
[ -n "$PROMPT" ] && { WHARGS+=(--prompt "$PROMPT"); echo "using --prompt glossary: $PROMPT"; }

echo "transcribing (warm) ..."
START=$(python3 -c 'import time;print(time.time())')
"$WHISPER" "${WHARGS[@]}" >/dev/null 2>"$STDERR"
END=$(python3 -c 'import time;print(time.time())')
WALL=$(python3 -c "print(round($END-$START,1))")

echo ""
echo "=== TIMING ==="
LANG="$(python3 -c "import json;print(json.load(open('$JSON'))['result']['language'])")"
echo "detected language : $LANG"
echo "audio duration    : ${AUDIO_DUR}s  ($(python3 -c "print(f'{$AUDIO_DUR/60:.1f} min')"))"
echo "warm wall clock   : ${WALL}s  ($(python3 -c "print(f'{$WALL/60:.1f} min')"))"
python3 -c "print(f'x-factor          : {$AUDIO_DUR/$WALL:.1f}x realtime')"

# Build compact file (+ heuristic speaker guess) and print accuracy evidence.
python3 - "$JSON" "$COMPACT" <<'PY'
import json, sys
json_path, compact_path = sys.argv[1], sys.argv[2]
d = json.load(open(json_path))
segs = d["transcription"]

def hms(ms):
    s, ms = divmod(int(ms), 1000); h, s = divmod(s, 3600); m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

# --- model-free speaker guess (heuristic, no deps) ---
# Toggle speaker on a long silent gap between segments (likely a turn change).
# Explicitly approximate: 2 labels (A/B), never asserted as ground truth.
GAP_MS = 1200
spk = 0; prev_end = None; rows = []
for s in segs:
    a, b = s["offsets"]["from"], s["offsets"]["to"]
    txt = s["text"].strip()
    if prev_end is not None and (a - prev_end) > GAP_MS:
        spk ^= 1
    rows.append((a, b, "AB"[spk], txt))
    prev_end = b

with open(compact_path, "w") as f:
    f.write("# start | end | speaker(guess) | text   (speaker = heuristic gap-based, approximate)\n")
    for a, b, sp, txt in rows:
        f.write(f"{a/1000:.2f} | {b/1000:.2f} | Speaker {sp} | {txt}\n")

n = len(rows)
turns = sum(1 for i in range(1, n) if rows[i][2] != rows[i-1][2])
print(f"\n=== COMPACT FILE ===")
print(f"segments          : {n}")
print(f"speaker turns      : {turns} (guess), labels used: {sorted(set(r[2] for r in rows))}")

# --- 3 excerpts: start / middle / end ---
picks = [("START", rows[min(2, n-1)]), ("MIDDLE", rows[n//2]), ("END", rows[max(n-3, 0)])]
print(f"\n=== ACCURACY EXCERPTS ===")
for label, (a, b, sp, txt) in picks:
    print(f"[{label} {hms(a)}–{hms(b)} Speaker {sp}] {txt}")

# --- domain-term scan ---
# List the proper nouns / brand names your videos use, so you can eyeball whether
# whisper mangled them. Customize this list for your domain.
terms = ["Kubernetes", "PostgreSQL", "GraphQL"]
full = " ".join(r[3] for r in rows).lower()
print(f"\n=== DOMAIN-TERM SCAN (flag manglings) ===")
found_any = False
for t in terms:
    c = full.count(t.lower())
    if c:
        found_any = True
        for a, b, sp, txt in rows:
            if t.lower() in txt.lower():
                print(f"  '{t}': {c}x  e.g. [{hms(a)}] …{txt[:80]}…"); break
if not found_any:
    print("  none of the tracked terms appear in this transcript.")
PY

echo ""
echo "=== FILE SIZES ==="
ls -lh "$JSON" "$COMPACT" | awk '{print "  "$5"\t"$NF}'
echo ""
echo "transcription done: SLUG=$SLUG"
