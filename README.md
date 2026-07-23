# clipear

clipear turns a long video (a YouTube/X link or a file on your Mac) into short, ready-to-share
clips, transcripts, and subtitles — all processed **locally on your own machine**, for free.
You drive it in plain English through [Claude Code](https://claude.com/claude-code); it transcribes,
suggests the best moments, waits for you to pick, then cuts the clips and writes subtitle files.

## Requirements

- A **Mac with Apple Silicon** (M1 or newer)
- **[Claude Code](https://claude.com/claude-code)** installed
- About **3 GB of free disk space** (most of it is the speech model)

That's it. No coding needed, no accounts, no API keys.

## Install by pasting this into Claude Code

Open Claude Code and paste this message:

```
I want to set up clipear, a free local video clipping tool.
Repo: https://github.com/Stefano-Cintioli/clipear
1. Check I'm on macOS with Apple Silicon; if not, stop and tell me what's supported.
2. Clone the repo to ~/clipear.
3. Follow its setup skill: install ffmpeg, yt-dlp and cmake with Homebrew (tell me first if Homebrew itself is missing), build whisper.cpp with Metal, download the large-v3-turbo model (~1.6 GB), verify with a sample transcription.
4. Show me evidence each step worked, then explain how to use /clipear.
Everything stays local on my machine. Do not install anything beyond what's listed.
```

Claude Code will **ask your permission before running each command** — reading those prompts
is encouraged, especially the first time. You can approve them one by one; nothing runs without
your say-so.

## How to use it

Once setup finishes, use the `/clipear` command with a source:

- **A YouTube video:**
  `/clipear https://www.youtube.com/watch?v=XXXXXXXXXXX`
- **A file already on your Mac:**
  `/clipear ~/Movies/interview.mp4`
- **Subtitles for a clip:** ask for them after processing —
  `make an SRT subtitle file for that clip` (you'll get a `.srt` you can import into CapCut or Premiere).

clipear transcribes, shows you a chapter map and a ranked list of the best moments, then **stops
and waits**. You reply with what to keep (chapter numbers, highlight numbers, or exact timecodes
like `12:30-18:45`), and it cuts the clips into a folder for you.

**One video per session** — run `/clear` before starting the next one so things don't get mixed up.

## Honest limitations

- **macOS Apple Silicon only** in v1. Intel Macs, Windows, and Linux aren't supported yet.
- **Clip starts snap to keyframes.** Lossless cuts can only begin on a keyframe, so a clip may
  include a couple of extra seconds at the front (trim it in your editor). No words are ever lost.
- **X / Twitter links are untested.** They use the same download path as YouTube but haven't been
  verified; they may need extra login steps.
- **YouTube changes break downloading now and then.** When downloads suddenly fail, the usual fix
  is to run `brew upgrade yt-dlp`.

## Privacy

Everything runs **on your machine**. No accounts, no API keys, no cloud services — your video and
its transcript are never uploaded anywhere. Transcription is done locally by whisper.cpp.

## Rights

Use clipear only on content you have the rights to download, clip, and republish.

## Contributing

Contributions are very welcome — **Windows and Linux support especially**. Open an issue or PR.

## License

MIT — see [LICENSE](LICENSE).
