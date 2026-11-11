# clipear

Turn a YouTube video or a camera file into clips you choose and approve. Use the
command line yourself, or let an MCP-capable agent read the transcript and propose
an edit. You review the exact plan before rendering.

The Python engine targets macOS on Apple Silicon and Intel, Windows, and Linux.
Native support is verified per platform, rather than inferred from portable code;
see [compatibility and test status](docs/compatibility.md).

## What you can make

- **Clean clips:** MP4 files with no burned text, ready for an editor such as
  CapCut or Premiere. Optional SRT files remain editable.
- **Finished clips:** MP4 files with captions burned into the picture, if your
  FFmpeg build supports libass. Choose clean, finished, or both in each edit plan.
- **Different editions:** change the brief, languages, clip ranges, landscape or
  portrait framing, caption text, playback speed, and encoding quality per plan.

Source framing, 16:9, 9:16, 1:1, and 4:5 outputs support padding or a fixed crop.
Preview the framing before approval. There is no automatic face tracking or native
CapCut project export. Output MP4s use H.264 and AAC when the source has audio.

Caption cues use source timestamps. If a selected cut crosses a cue, the plan
reports a boundary conflict and approval/export are blocked. Ask the agent to
provide corrected source-aligned cues, select the complete cue, or export clean
clips without captions. The engine never guesses which words were spoken inside
a partial cue. Reading-speed and line-count warnings are shown for review too.

## Start here

You need Python 3.11 or newer, FFmpeg/ffprobe, and a whisper.cpp executable plus a
Whisper model for local transcription. The Python install includes yt-dlp and the
MCP SDK. No model API key is required by clipear; an agent service you choose may
have its own account, pricing, and data policy.

Follow the [step-by-step setup](docs/setup.md) for your computer. If Python and the
media tools are already installed, clone this repository, open its folder, and run:

**macOS / Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m clipear doctor
```

**Windows PowerShell**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m clipear doctor
```

Use a Python version you actually have installed, at least 3.11. `doctor` reports
missing dependencies; it does not install tools, download a model, or establish
that a full transcription/render succeeded. Confirm the checks you need before
processing a video.

## Make your first clips

The examples below use `clipear` after activating the virtual environment. You can
instead use `.venv/bin/python -m clipear` on macOS/Linux or
`.\.venv\Scripts\python.exe -m clipear` on Windows.

1. **Import one source.** Run from a folder containing a camera file, or configure
   an allowed input folder as explained in [setup](docs/setup.md#input-folders-and-storage).

   ```sh
   clipear import "interview.mp4"
   # Or:
   clipear import "https://www.youtube.com/watch?v=VIDEO_ID"
   ```

   The command returns a job ID. Check `clipear job JOB_ID` until it reports success,
   then take the source ID from its result. IDs in these examples are placeholders:
   replace them with the returned values. Camera originals are copied into managed
   storage, leaving the originals untouched.

2. **Transcribe and inspect.**

   ```sh
   clipear transcribe SOURCE_ID
   clipear job JOB_ID
   clipear transcript SOURCE_ID
   ```

   Transcription is another background job. Wait for its success before reading
   the transcript. A connected agent can suggest chapters or highlights from
   this text; clipear does not independently rank moments.

3. **Describe the edit.** Copy [examples/edition.json](examples/edition.json), change
   its brief, language, and clip times to match your source, then save it as
   `edition.json`.

   ```sh
   clipear plan SOURCE_ID --file edition.json
   clipear show-plan PLAN_ID
   clipear preview PLAN_ID
   clipear job JOB_ID
   ```

   Preview generates framing stills. Check them, the exact retained ranges, and
   any corrected or translated caption text. `playback_speed` changes the video's
   speed and retimes its audio/subtitles; `quality` controls encoding effort.
   Editorial pace in the brief is a separate instruction to your agent.

4. **Approve the plan yourself.** Open the local browser review:

   ```sh
   clipear review PLAN_ID
   ```

   Or run `clipear approve PLAN_ID` in an interactive terminal and follow its
   confirmation prompt. An MCP agent has no approval tool. Approval binds the
   exact plan revision and source fingerprint; changing the plan requires fresh
   approval.

5. **Render and inspect the result.**

   ```sh
   clipear render PLAN_ID
   clipear job JOB_ID
   ```

   The completed job lists output files and verification results. Open the videos
   to check speech, cuts, framing, and captions before sharing. Background jobs
   retain their status after a client disconnect; they still depend on the
   processing computer remaining running.

To revise an edition, run `clipear plan SOURCE_ID --file edition.json --plan-id PLAN_ID`.
Inspect and approve the new revision. To add finished captions after a clean
delivery, update the caption cues and delivery mode and review that revision.

## Use it with an agent

Read [AGENTS.md](AGENTS.md) for the shared agent workflow. Project skills are in
`.agents/skills/clipear/` and `.claude/skills/`; they point to those same rules.
They do not install global skills or change your agent settings.

An MCP desktop client should launch the virtual environment's Python by its full
absolute path. Activating a terminal environment does not give a separately
launched desktop app the same PATH. For a terminal check, replace the example path:

```sh
"/absolute/path/to/clipear/.venv/bin/python" -m clipear mcp --transport stdio
```

On Windows, start the authenticated HTTP server in a separate PowerShell window
and connect your agent to it. Windows stdio clients can terminate descendant
workers when a chat disconnects, so that transport rejects background operations.
See the [Windows MCP instructions](docs/setup.md#connect-an-mcp-client).

Configure your client using the [platform examples](docs/setup.md#connect-an-mcp-client)
and [examples/mcp.json](examples/mcp.json). Set its `command` to that absolute
Python path and its arguments to `-m clipear mcp --transport stdio`. A bare
`clipear` command works only if that client can actually find the installed entry
point on its PATH. `doctor` also returns `mcp_command` using the Python executable
that ran the check. The client can inspect setup, import,
transcribe, read transcripts, propose plans, generate previews, request approved
renders, and poll jobs. The human still approves through the separate browser or
terminal review. See [MCP setup](docs/setup.md#connect-an-mcp-client) for HTTP and
remote-worker details.

Client configuration formats vary. A working MCP transport is not proof that a
particular Claude, Codex, ChatGPT, or Grok native app has been connected and tested.

## Privacy and boundaries

Media processing and whisper.cpp transcription happen on the processing host you
choose. A local installation keeps those files on that computer. A remote worker
processes files on its own host. YouTube import contacts YouTube; tool/model
installation also requires downloads.

A connected cloud agent receives the transcript and any other information you
supply through its tools or chat. clipear cannot override that provider's handling
of the data. Human approval is enforced at the MCP/API boundary; an agent with
unrestricted access to the same operating-system account can bypass local state.
Read [security and data handling](docs/security.md) before remote use.

## Legacy scripts

The Bash scripts under `scripts/` remain available for the original Apple Silicon
workflow. In particular, `scripts/setup.sh` still builds the older Mac-specific
setup, and the old cut script defaults to stream copy with keyframe limits. They
are separate from the portable Python/MCP workflow; the new engine encodes exact
clip ranges. See [compatibility](docs/compatibility.md#legacy-workflow).

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI defines Python 3.11/3.12 checks for Linux, Windows, Intel Mac, and Apple Silicon
Mac. It installs FFmpeg for real media fixtures. Whisper transcription needs an
external executable/model and is checked separately when available; a configured
CI matrix is not a passed native-platform run.

Use only content you have the rights to download, edit, and republish.
MIT — see [LICENSE](LICENSE).
