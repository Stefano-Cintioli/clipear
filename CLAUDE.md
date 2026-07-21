# clipear — hard rules

- Default cut = ffmpeg stream copy (`-c copy`). Never re-encode unless explicitly asked for "precise" mode.
- Never commit media or secrets. `.gitignore` must cover `*.mp4 *.mov *.wav *.m4a downloads/ work/ output/ .env*` and the `whisper.cpp/` build + models.
- One video per session. Run `/clear` before starting another so transcripts and picks don't bleed across videos.
- Chapters and summaries in the same language as the video.
- After each stage, run its check and show the evidence — never report success without verification.
