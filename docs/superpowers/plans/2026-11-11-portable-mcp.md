# Portable clipear MCP Implementation Plan

> For agentic workers: use subagent-driven-development/executing-plans within the user's approved scope. No extra approval or execution-method question: Stefano explicitly requested implementation.

**Goal:** one portable clipping engine, MCP interface, human approval and CLI fallback in the reusable clipear repository.
**Architecture:** independent media and transport modules behind persisted jobs/plans; host tools supply editorial reasoning; approval is outside MCP.
**Tech stack:** Python 3.11+, FFmpeg/ffprobe, whisper.cpp, yt-dlp 2026.10.26, official MCP SDK 2.3.0, SQLite, standard-library unittest.
**Spec:** `docs/superpowers/specs/2026-11-11-portable-mcp-design.md`.

## Global constraints

No changes to private clip-agent, no media/secrets/job data committed, no hosted public product or paid service. All MCP approval is human-only outside the tool list. Default local transport and CPU encoding; native platform/provider status must be stated accurately. Keep one engine shared by CLI and MCP. Protect main via feature branch; existing public checkout was clean. Native worktree discovery needed a different ref contract, so this reversible change uses a local feature branch in the current checkout instead of adding another project root.

## Review focus

1. Plan changed after approval must fail rendering; queued jobs must use frozen snapshots.
2. Sources, output identifiers, URL arguments and subtitle text must not escape allowed directories or become shell/filtergraph injection.
3. No model-provided boolean can grant approval; MCP exposes no approval capability.
4. Long-running workers must survive client disconnect and report actual failures; concurrent work must not corrupt SQLite state or mix job outputs.
5. Actual media dimensions/audio/timestamps/captions must match plan, including portrait sources, silent sources and speed changes. Platform CI claims need real evidence.

## Tasks

- [x] **Task 1: storage, validation, approval and detached jobs (root).** New `src/clipear/{__init__,__main__,config,store,service,worker,cli,review}.py`, `pyproject.toml`, `tests/test_state.py`, `tests/test_jobs.py`. First failing tests assert unapproved render rejected; changed goal/output/cue/source digest invalidates approval; NaN/ranges/path escapes rejected; jobs claim once; snapshot survives later plan edits. Implement and run full unittest discovery.
- [x] **Task 2: portable media and captions (media implementer).** New `src/clipear/media.py`, `src/clipear/captions.py`, `tests/test_media.py`, `tests/test_captions.py`. Read legacy scripts first. Tests before implementation: local copy immutable, argument paths with spaces, silent source, actual FFmpeg trim duration, every output ratio crop/pad, speed/audio/cue retiming and clean versus finished captions. May reuse/adapt generic Python logic from private repo read-only, never job records or fixed personal paths. Source import/download/transcription have explicit errors and retained logs. Interface is exactly the spec's Media class.
- [x] **Task 3: MCP adapter and protocol tests (transport implementer).** New `src/clipear/mcp_server.py`, `tests/test_mcp.py`, `examples/mcp.json`, optional bounded HTTP artifact access only for registered outputs. Use pinned SDK 2.3.0 actual API. Adapter delegates to Service, tools include setup/import/transcribe/transcript/plan/preview/render/job status; no approve tool or caller-controlled home/config. Real stdio initialize/list/call tests, no stdout noise; Streamable HTTP requires bearer token and rejects unauthorized requests, local bind default. Long calls return job ids. No arbitrary shell/file-read tools.
- [x] **Task 4: documentation, setup and CI (docs implementer).** Rewrite `README.md`, `CLAUDE.md`, `.claude/skills/clipear{,-setup}/SKILL.md`; create `AGENTS.md`, `.agents/skills/clipear/SKILL.md`, `examples/edition.json`, `docs/{setup,security,compatibility}.md`, `.github/workflows/test.yml`; update `.gitignore`. Explain approved flow, source versus job config, exact CLI, current privacy boundaries, optional HTTP and actual compatibility status. Keep legacy scripts labelled, do not break old scripts. Cross-platform CI, standard-library tests, install package in clean venv, ffmpeg smoke; whisper external/model sample only when available.
- [x] **Task 5: integrated verification/review (root + fresh reviewer).** Install new dependencies in ignored venv, no global configuration edits; test package/CLI, approval web/TTY and actual source→transcription→plan→approval→preview→clean/finished exports. Verify actual SDK over stdio+HTTP, disconnected job persistence, all source/media/secret exclusions. Record evidence in `docs/verification.md`; fresh code review on current diff, resolve material issues with regression tests. Native Windows/Linux/Intel Mac validation needs CI/remote evidence; never infer it from Apple Silicon success.

## Service interface contract

`Service(settings)` methods:
- `check_setup() -> dict`
- `import_source(source: str) -> dict` returns `{job_id, status}`; successful job result `{source_id, info, path, sha256}`.
- `transcribe_source(source_id: str, language: str='auto', glossary: str='') -> dict` returns job.
- `get_transcript(source_id: str, offset: int=0, limit: int=200) -> dict` returns `{source_id, language, segments, offset, total, next_offset}`.
- `create_edit_plan(source_id: str, clips: list[dict], brief: dict|None=None, outputs: list[dict]|None=None, captions: dict|None=None, delivery: str='clean', playback_speed: float=1.0, quality: str='balanced', plan_id: str|None=None) -> dict` returns plan record with id/revision/digest/document/approved plus human approval CLI instructions. Optional plan_id revises that source's plan.
- `get_edit_plan(plan_id: str) -> dict`
- `preview_edit_plan(plan_id: str) -> dict` returns job.
- `render_approved_plan(plan_id: str) -> dict` returns job only if approved exact digest/revision/current source hash.
- `get_job(job_id: str) -> dict` returns id/kind/status/progress/message/result/error/created_at/updated_at.

Settings fields: `home: Path`, `ffmpeg: str`, `ffprobe: str`, `yt_dlp: str` (executable; fall back to `[sys.executable,'-m','yt_dlp']` if absent), `whisper_cli: str|None`, `whisper_model: Path|None`, `input_roots: tuple[Path,...]`. `Settings.from_env(home: str|Path|None=None)` reads `CLIPEAR_HOME`, `CLIPEAR_FFMPEG`, `CLIPEAR_FFPROBE`, `CLIPEAR_YT_DLP`, `CLIPEAR_WHISPER`, `CLIPEAR_MODEL`, `CLIPEAR_INPUT_ROOTS` (os.pathsep-separated; default current directory); no HOME override. Machine configuration is host-controlled, not an MCP tool argument.

## Verification commands

`.venv/bin/python -m unittest discover -s tests -v` (all pass), `.venv/bin/python -m clipear doctor` (actual dependency status), wheel build/install into a separate clean venv then CLI help and MCP client smoke. Actual FFmpeg probe checks are in media tests. Review must inspect subprocess boundaries, persisted approval and source/snapshot handling beyond green tests.
