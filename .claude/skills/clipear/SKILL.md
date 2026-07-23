---
name: clipear
description: Turn a long video (YouTube URL, X URL, or local file path) into short social clips, transcripts, and subtitles. Runs the local clipear pipeline — ingest (h264/mp4, stream-copy safe), transcribe (whisper.cpp large-v3-turbo on Metal, auto-detect language), analyze into a chapter map + ranked highlight candidates, then after the user picks, cut losslessly and deliver. Also does SRT subtitles (sidecar), in-session translation, and filler detection/removal. Manual trigger only.
disable-model-invocation: true
---

# clipear

Local, free pipeline: long video in → transcript, chapters, subtitles → user picks →
lossless clips + SRT in the output folder. See `README.md` for setup and `CLAUDE.md` for
the hard rules. Never commit media or secrets. First-time setup: run the `clipear-setup` skill.

`$ARGUMENTS` = one source: a YouTube URL, an X URL, or a local file path.

## One video per session
Process exactly ONE video per session. Tell the user to `/clear` before starting another.

## Core workflow (clipping)

### 0. Glossary check
If this is a new content vertical (new brands, products, or people), remind the user to
add those terms to `prompts/whisper-glossary.txt` first — it's auto-loaded at transcription
and prevents proper-noun manglings.

### 1. Ingest — `scripts/ingest.sh "$ARGUMENTS"`
h264/mp4 only (stream-copy safe); STOPS with options if a video has no h264 stream. Local
files skip download. Produces the 16 kHz mono WAV. Show the codec/resolution/duration evidence.

### 2. Transcribe — `scripts/transcribe.sh <slug>`
whisper.cpp large-v3-turbo on Metal, auto-detect language, glossary auto-loaded. Show
detected language, x-factor, excerpts, domain-term scan. If a name is still mangled, add it
to the glossary and re-run once.

### 3. Analyze — follow `prompts/analyze.md` exactly
Read ONLY `work/<slug>.segments.txt` (never the word JSON). Output in the video's language.
Chapter map (primary) + 15–20 ranked highlight candidates with a mandatory compliance flag.

### 4. STOP — wait for picks
Present both views and wait. User replies with chapter IDs, highlight IDs, or raw ranges.
**Never cut without picks.**

### 5. Cut & deliver — write a picks file, run `scripts/cut.sh <slug> <source-url> <picks-file>`
Lossless stream copy with keyframe-padded start. `clip_NN_<topic>.mp4` in pick order →
`$OUTPUT_DIR/<slug>/`. Writes `notes/<slug>.md`. Show per-clip ffprobe evidence (codec/res
identical to master = no re-encode) and confirm `git status` is clean.

## Subtitles (SRT sidecar) — `scripts/subtitles.sh <slug> [--lang <code>]`
Produces `$OUTPUT_DIR/<slug>/<slug>.srt` — short, one-line cues that import cleanly into
CapCut / Premiere. **v1 outputs SRT only; no burned-in captions.** After generating:
- **Fix proper nouns:** review the SRT against the glossary and correct obvious
  mis-transcriptions of brands/names; change nothing else.
- Deliver the `.srt` alongside the video for the editor to style.

## Translation (in-session, no API) — agent task, not a script
To translate subtitles, the agent translates the SRT text **in-session** (never via a paid
API or key). Rules: keep **every timestamp block byte-for-byte identical** (index + `-->`
times), translate only the text lines, and keep glossary proper nouns unchanged. Write to
`<slug>.<targetlang>.srt` (e.g. `talk.en.srt`). This is how ES↔EN (or any pair) is done.

## Filler detection — `scripts/find-fillers.py <slug.json> [fillers...]`
Lists every filler occurrence with a 3-word context window and per-word counts, read from
the word JSON (never dumps the JSON). Default fillers are English; pass your own for the
video's language. Use the context to tell real words from fillers before removing anything.

## Filler removal (precise mode, re-encodes) — `scripts/remove-fillers.py <slug.json> <source> <out> <fc.txt> [fillers...]`
Cuts the listed fillers and re-encodes the whole video once with `h264_videotoolbox`,
keeping a ~150 ms buffer around neighbouring words so nothing sounds chopped. Reports
before/after duration and number of cuts. Only run after the user approves which fillers.

## Failure handling
On any stage failure: one-line diagnosis, then stop and wait. No auto-retry, no silent
fallback. If ingest starts failing broadly, `brew upgrade yt-dlp` is the first fix.
