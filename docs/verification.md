# Verification record

Local verification completed on 2026-11-11, Apple Silicon macOS, Python 3.12.13,
FFmpeg/ffprobe 8.1.2, MCP SDK 2.3.0 and yt-dlp 2026.10.26.

## Automated checks

`python -m unittest discover -s tests -v`: **65 tests passed**, no skips, in
50.210 seconds on the final verification run. Checks include real FFmpeg exports,
approval invalidation, frozen job snapshots, unexpected worker exits, caption
boundaries, path restrictions, stdio reconnection and authenticated HTTP.

The production MCP integration test imports real generated media, reconnects,
proposes an edit, verifies unapproved rendering fails, records fixture-only
approval outside MCP, renders, reconnects and checks the resulting H.264/AAC
media. It uses four actual stdio sessions on macOS/Linux and four actual network
HTTP sessions on every platform. Windows additionally checks actual stdio
background rejection with no queued jobs. The fixture approval is test setup,
not an agent approval capability.

A wheel was built and installed into a second clean virtual environment. Package
version, CLI entry point, dependency consistency, MCP startup and bundled font
and license inclusion were checked. No global agent configuration was changed.

## Real media checks

- A generated 11-second camera-style MP4 containing the public-domain JFK speech
  sample from whisper.cpp was imported and transcribed by an existing local
  whisper.cpp executable using the large-v3-turbo model and Apple M4 Metal.
- The complete 0–10.4 second spoken cue produced four MP4 files: clean and finished
  exports at 640×360 and 360×640, plus two SRT files. Actual duration, codecs,
  dimensions and SHA-256 hashes passed. The imported source hash remained intact.
- Rendering without approval and approval with a partial source caption cue were
  both rejected. Caption readability warnings remained visible for human review.
- A current upstream yt-dlp YouTube fixture, `gHKT4uU8Zng`, imported successfully
  as 1920×1080 H.264 media (5.021 seconds). A clean 0–3 second export passed media
  checks. The older `BaW_jenozKc` fixture was unavailable; that failed attempt was
  retained instead of being counted as a successful download.
- The human review page returned HTTP 200, loaded both framing images and had no
  browser errors. Desktop (1280 pixels) and mobile (390 pixels) screenshots were
  visually inspected. The test server was then stopped.

Local detailed results and screenshots are under ignored `.clipear/verification/`;
source media, transcripts, model files, job databases and personal paths are not
part of this repository.

## Independent review

A fresh review found three issues: preview/revision mismatch during review,
worker exits leaving jobs nonterminal, and full caption text spanning a partial
cut. Each received a regression test and a fix. Scoped independent re-review
found all three addressed with no new actionable findings. A final read-only
publication review found no blockers in CI, setup or compatibility documentation.

## Scope and limits

The [CI workflow](../.github/workflows/test.yml) exercises Python 3.11/3.12 on
Ubuntu, Windows, Intel macOS and Apple Silicon macOS. Its actual results are
available from [GitHub Actions](https://github.com/Stefano-Cintioli/clipear/actions/workflows/test.yml).
See the latest [PR #1 checks](https://github.com/Stefano-Cintioli/clipear/pull/1/checks)
for the release commit's native results. The first run caught portability gaps:
fixture cleanup before worker/observer exit, implicit Windows decoding in two
caption tests, Mac FFmpeg without libass, and Windows stdio clients killing
descendants on disconnect. Fixes use explicit observer joins, UTF-8 reads,
feature-checked caption-enabled binaries and separately hosted authenticated HTTP
for Windows background processing. The full matrix is rerun for the correction.

Native Claude, Codex, ChatGPT and Grok apps have not been registered or tested by
this run. Successful MCP protocol checks do not prove an app-specific integration.
No public website, paid service or remote worker was provisioned. A detached
worker can survive a client disconnect; unexpected exits are recorded while its
parent observer is alive. This is not a durable scheduler across host shutdowns.
See [compatibility](compatibility.md) and [security](security.md).
