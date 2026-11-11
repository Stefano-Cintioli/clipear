# Portable MCP build progress

Implementation baseline: a180da33449b33ef853777ae8d916f86456770b9. Reusable source and documentation stay separate from private production jobs.

- Planning/source inspection complete. New workflow keeps job data out of Git, uses one engine for CLI and MCP, and human-only approval.
- Official package metadata verified: MCP 2.3.0 (Python >=3.10), yt-dlp 2026.10.26 (Python >=3.11). Runtime Python 3.12.13, FFmpeg/ffprobe 8.1.2 available. Existing read-only whisper.cpp runtime/model can support a local sample without another model download.
- Baseline has no test suite or Python package. Tests are introduced before functional implementation.
- Tasks 1–4 implemented: portable media/captions, SQLite plans/jobs, human CLI/browser review, nine-tool MCP stdio/authenticated HTTP, setup/docs and eight-job CI matrix. No private production jobs copied.
- Test-first approval, media and protocol checks passed locally. Actual YouTube import/export passed using a current five-second upstream yt-dlp fixture; the historical fixture is unavailable and its failure was retained. A public-domain speech sample passed real local Whisper transcription and clean/finished landscape/portrait export.
- Fresh review found three concrete issues: preview/revision mismatch during review, unexpected worker exit leaving nonterminal jobs, and source-cue text crossing cuts. Each was reproduced, fixed in one wave with regression tests, then passed scoped independent re-review. No open important findings.
- Final suite after native portability fixes: 65 tests passed with no skips. Real Whisper/camera and YouTube import/export checks passed, source and output hashes matched, the wheel installed cleanly, and desktop/mobile human review was inspected. See [verification record](verification.md).
- [PR #1](https://github.com/Stefano-Cintioli/clipear/pull/1) publishes the implementation and records the native checks. The initial run exposed test cleanup racing worker exit, default Windows decoding in caption tests, Mac FFmpeg builds without libass, and Windows stdio client termination of descendant workers. These have focused fixes and regression coverage; Windows background processing uses separately launched authenticated HTTP. Native provider connections are not claimed.
