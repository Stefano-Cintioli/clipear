#!/usr/bin/env python3
# clipear — filler REMOVER (precise mode, macOS). Reads the whisper word JSON,
# removes the given filler words, and re-encodes the source once (h264_videotoolbox)
# with the fillers cut out. Keeps a buffer around adjacent words so speech isn't chopped.
# Usage: remove-fillers.py <slug.json> <source.mp4> <out.mp4> <fc_out.txt> [fillers...]
import sys, re, json, unicodedata, subprocess

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w]", "", s).lower()

json_path, src, out, fc_path = sys.argv[1:5]
fillers = [f.lower() for f in (sys.argv[5:] or ["uh", "um", "like"])]
uni = {f for f in fillers if " " not in f}
bi  = [f.split() for f in fillers if " " in f]
BUF = 0.150  # seconds of breathing room kept next to neighbouring words

d = json.load(open(json_path))
words = []  # [clean, start_s, end_s]
for seg in d["transcription"]:
    for t in seg.get("tokens", []):
        raw = t.get("text", "")
        if raw.startswith("[_") or "-->" in raw or not raw.strip():
            continue
        s0, s1 = t["offsets"]["from"] / 1000, t["offsets"]["to"] / 1000
        if raw.startswith(" ") or not words:
            words.append([norm(raw), s0, s1])
        else:
            words[-1][0] += norm(raw); words[-1][2] = s1

is_filler = [False] * len(words)
for i, w in enumerate(words):
    if w[0] in uni:
        is_filler[i] = True
for parts in bi:
    pn = [norm(p) for p in parts]
    for i in range(len(words) - len(parts) + 1):
        if [words[i+j][0] for j in range(len(parts))] == pn:
            for j in range(len(parts)):
                is_filler[i+j] = True

DUR = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]).strip())

cuts = []
i = 0
while i < len(words):
    if not is_filler[i]:
        i += 1; continue
    j = i
    while j + 1 < len(words) and is_filler[j + 1]:
        j += 1
    ws, we = words[i][1], words[j][2]
    prev_end = words[i-1][2] if i > 0 else 0.0
    next_start = words[j+1][1] if j + 1 < len(words) else DUR
    cs = max(ws, prev_end + BUF)
    ce = min(we, next_start - BUF)
    if ce - cs >= 0.05:
        cuts.append((cs, ce))
    else:
        print(f"  SKIP (too tight to cut safely): {ws:.2f}-{we:.2f}s")
    i = j + 1

cuts.sort()
merged = []
for cs, ce in cuts:
    if merged and cs <= merged[-1][1]:
        merged[-1] = (merged[-1][0], max(merged[-1][1], ce))
    else:
        merged.append((cs, ce))

keeps = []
pos = 0.0
for cs, ce in merged:
    if cs > pos:
        keeps.append((pos, cs))
    pos = ce
if pos < DUR:
    keeps.append((pos, DUR))

removed = sum(ce - cs for cs, ce in merged)
after = sum(ke - ks for ks, ke in keeps)
print(f"filler cuts applied : {len(merged)}")
print(f"before duration     : {DUR:.2f}s")
print(f"removed total       : {removed:.2f}s")
print(f"after  duration     : {after:.2f}s  (keep segments: {len(keeps)})")

parts, labels = [], []
for k, (ks, ke) in enumerate(keeps):
    parts.append(f"[0:v]trim=start={ks:.3f}:end={ke:.3f},setpts=PTS-STARTPTS[v{k}]")
    parts.append(f"[0:a]atrim=start={ks:.3f}:end={ke:.3f},asetpts=PTS-STARTPTS[a{k}]")
    labels.append(f"[v{k}][a{k}]")
fc = ";\n".join(parts + [f"{''.join(labels)}concat=n={len(keeps)}:v=1:a=1[v][a]"])
open(fc_path, "w").write(fc)

cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
       "-filter_complex_script", fc_path, "-map", "[v]", "-map", "[a]",
       "-c:v", "h264_videotoolbox", "-b:v", "40M", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", out]
print("\nffmpeg command:")
print("  " + " ".join(cmd))
subprocess.check_call(cmd)
print("\ndone ->", out)
