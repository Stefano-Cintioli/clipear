#!/usr/bin/env python3
# clipear — filler finder. Reconstructs words from the whisper word/token JSON and
# lists filler occurrences with surrounding context and per-word counts. Reads the
# JSON from disk; prints ONLY the findings (never dumps the JSON).
#
# Usage: find-fillers.py <slug.json> [filler1 filler2 ...]
#   Fillers default to a small English set. Pass your own for your language, e.g.
#   spoken markers like "uh" "um" "like" "you know" (multi-word terms are supported).
import sys, re, json, unicodedata

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w]", "", s).lower()

def hms(ms):
    s = ms / 1000; m = int(s // 60); return f"{m:02d}:{s % 60:05.2f}"

json_path = sys.argv[1]
fillers = [f.lower() for f in (sys.argv[2:] or ["uh", "um", "like", "you know"])]
uni = [f for f in fillers if " " not in f]
bi  = [f for f in fillers if " " in f]

d = json.load(open(json_path))
# reconstruct words: a token whose raw text starts with a space begins a new word
words = []  # (clean, raw, start_ms)
for seg in d["transcription"]:
    for t in seg.get("tokens", []):
        raw = t.get("text", "")
        if raw.startswith("[_") or "-->" in raw or not raw.strip():
            continue
        st = t["offsets"]["from"]
        if raw.startswith(" ") or not words:
            words.append([norm(raw), raw.strip(), st])
        else:
            words[-1][0] += norm(raw); words[-1][1] += raw

hits = []
counts = {f: 0 for f in fillers}
for i, (clean, _raw, st) in enumerate(words):
    if clean in uni:
        ctx_b = " ".join(w[1] for w in words[max(0, i-3):i])
        ctx_a = " ".join(w[1] for w in words[i+1:i+4])
        hits.append((st, clean, f"{ctx_b}  «{words[i][1]}»  {ctx_a}"))
        counts[clean] += 1
for f in bi:
    parts = f.split()
    for i in range(len(words) - len(parts) + 1):
        if [words[i+j][0] for j in range(len(parts))] == [norm(p) for p in parts]:
            st = words[i][2]
            ctx_b = " ".join(w[1] for w in words[max(0, i-3):i])
            ctx_a = " ".join(w[1] for w in words[i+len(parts):i+len(parts)+3])
            phrase = " ".join(words[i+j][1] for j in range(len(parts)))
            hits.append((st, f, f"{ctx_b}  «{phrase}»  {ctx_a}"))
            counts[f] += 1

hits.sort()
print(f"total words reconstructed: {len(words)}")
print(f"filler occurrences: {len(hits)}\n")
print(f"{'time':>7}  {'filler':<8}  context (3 words around)")
print("-" * 78)
for st, f, ctx in hits:
    print(f"{hms(st):>7}  {f:<8}  {ctx}")
print("\ncounts per filler:")
for f in fillers:
    print(f"  {f:<8}: {counts[f]}")
