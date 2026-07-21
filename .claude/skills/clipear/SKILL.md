---
name: clipear
description: Turn a long video (YouTube URL, X URL, or local file path) into short social clips. Runs the local clipear pipeline — ingest (h264/mp4, stream-copy safe), transcribe (whisper.cpp large-v3-turbo on Metal, auto-detect language), analyze into a chapter map + ranked highlight candidates with compliance flags, then after the user picks, cut losslessly (stream copy + keyframe padding) and deliver to the output folder. Manual trigger only.
disable-model-invocation: true
---

# clipear

Local, free pipeline: long video in → transcript + chapters → user picks segments →
lossless clips in the output folder, ready for editing. See `README.md` for setup and
`CLAUDE.md` for the hard rules. Never commit media or secrets.

`$ARGUMENTS` = one source: a YouTube URL, an X URL, or a local file path.

## One video per session
Process exactly ONE video per session. Tell the user to `/clear` before starting
another — a fresh context keeps transcripts and picks from bleeding across videos.

## Workflow

### 0. Glossary check (before running)
If this video is a **new content vertical** (new brands, product names, or people
whisper won't know), remind the user to add those terms to
`prompts/whisper-glossary.txt` first — it's auto-loaded at transcription and prevents
brand manglings. If it's the same domain as before, proceed.

### 1. Ingest
Run `scripts/ingest.sh "$ARGUMENTS"`.
- Downloads **h264/mp4 only** (stream-copy safe). If a video has no h264 stream, the
  script STOPS and lists options — do not work around it silently.
- Reports the resolution-vs-compatibility tradeoff when a higher resolution exists
  only in VP9/AV1. Surface that to the user.
- Local files skip download. Produces the 16 kHz mono WAV.
- Show the codec/resolution/duration-match evidence block.

### 2. Transcribe
Run `scripts/transcribe.sh <slug>` (slug is printed by ingest).
- whisper.cpp `large-v3-turbo` on Metal, auto-detect language, glossary auto-loaded.
- Show detected language, x-factor, the 3 accuracy excerpts, and the domain-term scan.
- If a brand/name is still mangled, add it to the glossary and re-run once.

### 3. Analyze
Follow `prompts/analyze.md` exactly:
- **Read ONLY** `work/<slug>.segments.txt` (the compact file). NEVER load the word JSON.
- Output in the **video's language**.
- **Chapter map is the primary output** — C1..Cn, full runtime, no gaps.
- **15–20 ranked highlight candidates** H1..Hn: cut range ≤60s snapped to sentence
  boundaries, score 1–10, verbatim quote, why it works, target audience, and a
  **mandatory compliance flag** (per your org's rules in analyze.md).
- Speaker labels in the file are a heuristic guess — attribute by content, stay neutral otherwise.

### 4. STOP — wait for picks
Present both views and **wait**. The user replies with chapter IDs (`C4`), highlight
IDs (`H1, H3`), and/or raw ranges (`12:30-18:45`). **Never cut without picks.**

### 5. Cut & deliver
Write a picks file (`topic-slug|start_sec|end_sec|compliance` per line, in pick order)
and run `scripts/cut.sh <slug> <source-url> <picks-file>`.
- Lossless stream copy with keyframe-padded start (no words lost, no re-encode).
- `clip_NN_<topic-slug>.mp4` in pick order → `$OUTPUT_DIR/<slug>/` (default `~/clipear-output`).
- Writes `notes/<slug>.md` (source, date, per-clip requested/actual/duration/size/compliance —
  no transcript content).
- Show the per-clip ffprobe evidence (codec/res identical to master = no re-encode),
  duration deltas, the output folder listing, and confirm `git status` is clean.

### Vertical (optional, on request)
Only if the user asks: preview a static 9:16 crop as a still, get approval, then
re-encode that clip to vertical. Default output stays lossless horizontal.

## Failure handling
On any stage failure: one-line diagnosis, then stop and wait. No auto-retry, no silent
fallback. If ingest starts failing broadly, `brew upgrade yt-dlp` is the first fix.
