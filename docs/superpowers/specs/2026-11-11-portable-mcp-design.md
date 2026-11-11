# Portable clipear engine and MCP

Scope: portable media processing, a small MCP surface, human confirmation, clean clips followed by optional finished exports. No hosted public website, paid service, account upload, media publication or changes to private job repositories are needed.

## Intended result

Improve the existing public MIT clipear repository, keeping private jobs separate. A human or an agent can process one YouTube source or camera file per job, inspect a transcript, propose an edition-specific plan, obtain human confirmation, then export clean editable MP4/SRT files or finished captioned videos. Codex, Claude and other MCP-capable agents use the same engine. Editorial reasoning/translation stays in the connected agent; no model API keys are bundled.

## Architecture

- Python 3.11+ package and CLI, using FFmpeg/ffprobe, yt-dlp and a configurable whisper.cpp binary/model. Paths use pathlib and subprocess argument lists; no Bash requirement in the new workflow. Software H.264 is the common baseline. Existing legacy scripts stay available but are labelled legacy.
- Jobs and artifacts live in configurable user storage, outside tracked source. SQLite stores source records, immutable job requests, edit-plan revisions and approvals. Detached workers return a job ID immediately and retain progress, errors and results after the MCP connection closes.
- A local stdio MCP plus authenticated Streamable HTTP serve the same tools. HTTP is single-user and localhost by default; running remotely requires TLS/network configuration and the user's token. It is not a multi-user hosted product or a native integration with every chat service. Camera files must be accessible on the processing host. Client configurations and protocol tests distinguish tested transports from unverified native apps.
- Native Windows testing showed that stdio clients can place the server and its descendants in a Job Object that terminates workers on disconnect. Windows stdio therefore rejects background operations; a separately started authenticated HTTP server provides Windows processing. The CLI and macOS/Linux stdio workflow remain available.
- File import is limited to host-configured input roots; URL ingest supports YouTube. Paths never become shell code. Source bytes are copied into job storage and fingerprinted. Original camera files are never edited.
- Human confirmation is through a separate interactive CLI or loopback browser review, never an MCP approval tool. Approval binds the exact normalized plan, source fingerprint and revision; changes invalidate it. A render job freezes the approved snapshot. This is an MCP/API boundary, not protection against a person or agent with unrestricted access to the same OS account/database.

## Job plan

`version`, `source_id`, `source_sha256`, `brief`, `clips`, `outputs`, `captions`, `delivery`, `playback_speed`, `quality`.

- Brief: goal, audience, language, tone, platforms, duration preference, pace, must-include/avoid topics, glossary and local/cloud processing context. Brief fields guide the connected agent; the engine does not pretend to independently rank highlights.
- Clips: stable id, title, source start/end seconds. Reject NaN/infinity, negative/empty/out-of-range intervals and unsafe identifiers.
- Outputs: name, ratio (`source`, `16:9`, `9:16`, `1:1`, `4:5`), height, fit (`pad` or `crop`), position (`left`, `center`, `right`). Source profile preserves source framing. Preview stills show framing before approval; no face tracking.
- Captions: mode (`none`, `sidecar`, `burn`), language and source-timeline cues (`start`, `end`, `text`). Default cues may come from the transcript; agent-supplied corrections/translations are visible in the plan. Trim/map cue timestamps per clip and playback speed. Surface reading-speed failures rather than silently losing words.
- Delivery: `clean`, `finished`, `both`. Clean clips have no burned text. Burn mode requires finished/both. No native CapCut project export; standard MP4/SRT works with external editors.
- Playback speed defaults to 1, allowed 0.5–2 with audio and subtitle retiming. Quality is `fast`, `balanced` or `quality`, distinct from editorial pace and playback speed.

## Public interfaces

`Settings.from_env(home=None)` resolves paths/executables/input roots. `Settings` exposes home, ffmpeg, ffprobe, yt_dlp, whisper_cli, whisper_model and input_roots. No personal absolute paths in tracked configuration.

`Media(settings)` provides:
- `inspect(path: Path) -> dict` (duration, width, height, streams/audio presence).
- `ingest(source: str, directory: Path) -> dict` with `path`, `sha256`, `info`.
- `transcribe(path: Path, directory: Path, language='auto', glossary='') -> dict` with `language`, `segments` (`start/end/text`), JSON evidence path.
- `preview(path: Path, directory: Path, plan: dict) -> list[dict]` with generated frame paths/profile/clip.
- `render(path: Path, directory: Path, plan: dict, segments: list, progress=None) -> dict` with `outputs` (`path/name/kind/sha256/probe`) and verification results. All final MP4s H.264/yuv420p, AAC when audio exists, square pixels; verify duration/dimensions and absence of unexpected audio loss. Source data/cues and approved snapshots remain immutable.

`Service(settings)` provides `check_setup`, `import_source`, `transcribe_source`, `get_transcript`, `create_edit_plan`, `get_edit_plan`, `preview_edit_plan`, `render_approved_plan`, `get_job`; signatures are pinned in the plan. Approve/review functions are CLI-only.

## Acceptance

Tests first for plan validation, approval/revision binding, inaccessible paths, detached-job state, transcript paging, subtitles/speed mapping, crop/pad dimensions and MCP no-self-approval. Actual FFmpeg fixtures verify clean/finished exports and source immutability. Read-only existing whisper runtime/model may be used with a public-domain sample, with outputs only in clipear's ignored storage. Use the official pinned MCP SDK and real clients to test initialize/list/call and failure paths over stdio and authenticated HTTP. CI defines Windows, Linux, Intel/ARM Mac coverage; report native platforms unverified until their runs pass. Do not claim remote provider/client support from SDK discovery alone.
