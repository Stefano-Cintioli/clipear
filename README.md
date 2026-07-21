# clipear

A local, free pipeline that turns a long video (YouTube/X link or local file) into a
handful of the best short clips for social — driven from [Claude Code](https://claude.com/claude-code)
as a skill. It transcribes the video, proposes a chapter map and ranked highlight
candidates, waits for you to pick, then cuts the clips **losslessly** and writes them
to an output folder, ready for your editor (CapCut, Premiere, etc.).

Everything runs on your machine. No paid APIs — transcription is local via whisper.cpp;
the transcript analysis happens inside your Claude Code session.

## What it does

1. **Ingest** — downloads the source as **h264/mp4 only** (so clips can be stream-copied
   without re-encoding) and extracts a 16 kHz mono WAV. Local files skip the download.
2. **Transcribe** — whisper.cpp `large-v3-turbo` on Metal, auto-detecting the language,
   with word-level timestamps and a compact per-segment transcript.
3. **Analyze** — produces a chapter map (primary) plus 15–20 ranked highlight
   candidates, each with a score, verbatim quote, target audience, and a compliance flag.
4. **You pick** the segments (chapter IDs, highlight IDs, or raw timecodes).
5. **Cut & deliver** — lossless stream copy with keyframe-padded starts, named
   `clip_NN_<topic>.mp4`, into your output folder, with a per-clip log.

## Requirements

- **Claude Code**
- **macOS on Apple Silicon** (this is what it was built and tested on — it uses Metal
  for whisper.cpp)
- **Homebrew**, and: `brew install ffmpeg yt-dlp cmake`
- **Python 3.12**
- **whisper.cpp** built with Metal + the `large-v3-turbo` model — install with the
  bundled script (below)

## Setup

```sh
git clone https://github.com/<your-account>/clipear.git
cd clipear
brew install ffmpeg yt-dlp cmake
scripts/setup-whisper.sh          # clones + builds whisper.cpp (Metal), downloads the model (~1.5 GB)
```

Output goes to `$OUTPUT_DIR/<slug>/`, default `~/clipear-output`. Point `OUTPUT_DIR` at
any folder you like (for example a cloud-synced one):

```sh
export OUTPUT_DIR="$HOME/my-synced-folder/clips"
```

Before transcribing a new topic, add the proper nouns/brand names your videos use to
`prompts/whisper-glossary.txt`, and adapt the compliance rules in `prompts/analyze.md`
to your org.

## Install the skill

Copy the skill so Claude Code can find it, then reload:

- **Project-scoped:** keep `.claude/skills/clipear/` in the repo (already there).
- **Global:** `cp -r .claude/skills/clipear ~/.claude/skills/clipear`

## Usage

In Claude Code:

```
/clipear <youtube-url | x-url | local-file-path>
```

It ingests, transcribes, shows the chapter map + ranked highlights, then **stops**.
Reply with your picks — chapter IDs (`C4`), highlight IDs (`H1, H3`), or raw ranges
(`12:30-18:45`) — and it cuts and delivers.

**One video per session.** Run `/clear` before the next one so transcripts and picks
don't bleed across videos.

## Limitations & honest notes

- **Clip starts are keyframe-padded.** Lossless stream copy can only cut on keyframes,
  so each clip begins on the keyframe at or just before your in-point — you get up to a
  few extra seconds of head, which you trim in your editor. It never loses your opening
  words, and it never re-encodes.
- **X/Twitter path is wired but untested.** It uses the same yt-dlp code path as YouTube
  but hasn't been validated against a real X video; X often needs `--cookies-from-browser`.
- **YouTube extraction breaks periodically.** When ingest suddenly starts failing, the
  first fix is almost always `brew upgrade yt-dlp`.
- Built and tested on Apple Silicon macOS. Other platforms may work with changes to the
  whisper.cpp build flags but are untested.

## Rights

Use this only on content you have the rights to download, clip, and republish.

## License

MIT — see [LICENSE](LICENSE).
