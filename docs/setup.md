# Setup

Set up clipear on the computer that will process the video. Start with a local
installation; a remote worker is optional. Nothing here requires an agent account
or model API key. A cloud agent you connect separately can have its own charges.

## 1. Get Python and the repository

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/).
On Windows, keep the Python launcher available. On Linux, your distribution may
package `python3-venv` separately. Install Git if you will clone the repository, or
download and unpack the repository ZIP from GitHub.

With Git installed:

```sh
git clone https://github.com/Stefano-Cintioli/clipear.git
cd clipear
```

A virtual environment keeps clipear's Python packages separate from other projects.
The [Python venv guide](https://docs.python.org/3/library/venv.html) explains the
platform differences.

**macOS / Linux**

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Use a version you have installed, at least 3.11. On Windows, you can run every
command with `.\.venv\Scripts\python.exe -m clipear`; no shell activation or
execution-policy change is needed. On macOS/Linux, the equivalent is
`.venv/bin/python -m clipear`. The shorter `clipear` examples below assume
the virtual environment is active.

The package installation brings in the versions of yt-dlp and the MCP SDK pinned
in [pyproject.toml](../pyproject.toml). It does not install FFmpeg, whisper.cpp, or a
speech model.

## 2. Install FFmpeg and ffprobe

FFmpeg reads camera formats and makes clips. ffprobe inspects source and output
files. Use the [FFmpeg download page](https://ffmpeg.org/download.html) for upstream
source and linked platform builds.

- **macOS:** check the build's caption capability before selecting it. The regular
  Homebrew `ffmpeg` formula can omit libass. On Apple Silicon, the official
  [Homebrew `ffmpeg-full` formula](https://formulae.brew.sh/formula/ffmpeg-full)
  supplies libass and x264 with prebuilt bottles. It is keg-only, so configure
  `CLIPEAR_FFMPEG` and `CLIPEAR_FFPROBE` to its executables, as shown below. Current
  bottle availability varies by OS/architecture; do not start a large source build
  on an Intel Mac assuming the same bottles exist. For Intel, the
  [Evermeet static builds](https://evermeet.cx/ffmpeg/) linked by FFmpeg provide
  libass and libx264; choose matching ffmpeg/ffprobe releases and configure their
  executable paths. Evermeet supplies third-party binaries; FFmpeg itself publishes
  source code. Do not install Homebrew silently.
- **Ubuntu / Debian:** your package manager provides `ffmpeg`, for example
  `sudo apt install ffmpeg`. Other Linux distributions use different package names
  or commands.
- **Windows:** download a Windows build linked by FFmpeg, unpack it, and make its
  `bin` folder available on PATH. It must contain both `ffmpeg.exe` and
  `ffprobe.exe`. You can instead set their explicit locations below.

Check the installed tools:

```sh
ffmpeg -version
ffprobe -version
clipear doctor
```

Clean video exports require an H.264 encoder; the common CPU baseline is libx264.
Burned captions also require libass and the FFmpeg `subtitles` filter. Builds can
differ even when they share a version number. Use `doctor` and a real small export
to check your build. See [FFmpeg's filter documentation](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1).

With Homebrew already installed on a supported Apple Silicon Mac, select its
full prebuilt formula explicitly:

```sh
brew install --force-bottle ffmpeg-full
export CLIPEAR_FFMPEG="$(brew --prefix ffmpeg-full)/bin/ffmpeg"
export CLIPEAR_FFPROBE="$(brew --prefix ffmpeg-full)/bin/ffprobe"
clipear doctor
```

This selects the keg-only binaries for clipear without replacing your system's
other FFmpeg installation. Give an MCP desktop client these same executable paths
in its environment; terminal exports alone may not reach it.

## 3. Add local transcription

clipear calls [whisper.cpp](https://github.com/ggml-org/whisper.cpp) on the processing
host. Choose an upstream release binary or build it using the upstream instructions.
You also need a compatible `ggml-*.bin` model. Smaller models are faster and use less
memory; they can be less accurate. Choose a multilingual model when you need
languages other than English. clipear does not force a large model download.

For a CPU baseline build, install CMake and a C++ toolchain for your platform,
then run these commands in a tools folder you own, outside the tracked repository:

```sh
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DGGML_METAL=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel
```

On macOS/Linux, the CLI is usually `build/bin/whisper-cli`. On Windows with a
multi-configuration generator, look in `build/bin/Release/whisper-cli.exe`. Confirm
the actual generated path. Follow whisper.cpp's upstream guidance if you choose
Metal, CUDA, Vulkan, or another accelerator; hardware acceleration is optional.

For example, download the multilingual `base` model from within whisper.cpp:

**macOS / Linux**

```sh
sh models/download-ggml-model.sh base
./build/bin/whisper-cli -m models/ggml-base.bin -f samples/jfk.wav
```

**Windows PowerShell**

```powershell
cmd /c models\download-ggml-model.cmd base
.\build\bin\Release\whisper-cli.exe -m models\ggml-base.bin -f samples\jfk.wav
```

A successful sample must produce plausible text and timestamps. A binary version
or file existence check alone does not prove transcription works.

Tell clipear where the executable and model are. Replace these example paths with
the real locations, then return to the clipear folder.

**macOS / Linux**

```sh
export CLIPEAR_WHISPER="/path/to/whisper.cpp/build/bin/whisper-cli"
export CLIPEAR_MODEL="/path/to/whisper.cpp/models/ggml-base.bin"
clipear doctor
```

**Windows PowerShell**

```powershell
$env:CLIPEAR_WHISPER = "C:\Tools\whisper.cpp\build\bin\Release\whisper-cli.exe"
$env:CLIPEAR_MODEL = "C:\Tools\whisper.cpp\models\ggml-base.bin"
.\.venv\Scripts\python.exe -m clipear doctor
```

Environment settings in a terminal apply to programs started from that terminal.
An MCP desktop client may need these values in its own server configuration.
Do not assume a desktop app reads your shell startup file.

## Input folders and storage

The host controls which camera-file folders clipear may import. The default allowed
input folder is the current working directory. Use an explicit folder rather than
granting access to your whole home directory.

For a CLI import, repeat `--input-root` if necessary:

```sh
clipear --input-root "/path/to/camera-files" import "/path/to/camera-files/interview.mp4"
```

For an MCP process, set `CLIPEAR_INPUT_ROOTS` in its environment. Multiple folders
are separated with `:` on macOS/Linux and `;` on Windows. All source paths are
paths on the processing host, even if the agent client is elsewhere.

Managed storage contains copied source media, a SQLite database, transcripts,
plans, approval records, jobs, logs, previews, and outputs. Defaults are:

- macOS: `~/Library/Application Support/clipear`
- Windows: `%LOCALAPPDATA%\clipear`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/clipear`

Set `CLIPEAR_HOME` or pass the global `--home` option to choose a different folder:

```sh
clipear --home "/path/to/clipear-data" doctor
```

Use the same home for CLI review and the MCP server so they see the same plans.
The explicit `--home` value overrides `CLIPEAR_HOME`. This storage is separate from
your Git checkout; do not place media, job state, or tokens into tracked files.

Host configuration is separate from an edition's creative choices:

- `CLIPEAR_HOME`: managed storage; `--home` overrides it.
- `CLIPEAR_INPUT_ROOTS`: allowed camera-file folders.
- `CLIPEAR_FFMPEG`, `CLIPEAR_FFPROBE`: executable names or paths.
- `CLIPEAR_YT_DLP`: downloader executable; the installed Python module is the fallback.
- `CLIPEAR_WHISPER`, `CLIPEAR_MODEL`: transcription executable and model.
- `CLIPEAR_HTTP_TOKEN`: HTTP bearer token, when that transport is used.

The MCP caller cannot change these host settings through tool arguments.

## Make and revise an edition

Follow the [first-clip workflow](../README.md#make-your-first-clips).
[examples/edition.json](../examples/edition.json) is a template, not a selection
for your video. Its example range is 5–20 seconds; replace it with reviewed ranges
inside your source duration.

Each edition defines:

- `brief`: goal, audience, language, tone, platforms, duration preference, pace,
  required/avoided topics, glossary, and processing context for the agent.
  `privacy_mode` can label the host `local` or `cloud`; it does not move processing,
  provision a cloud worker, choose an AI provider, or change the agent's privacy.
- `clips`: stable safe identifiers, titles, and source-timeline start/end seconds.
- `outputs`: names, aspect ratios, height, pad/crop fit, and fixed left/center/right
  positioning. `source` keeps the original framing. Inspect preview stills for crops.
- `captions`: `none`, `sidecar`, or `burn`; language; and optional source-timeline
  cues with `start`, `end`, and `text`. Without supplied cues, use the transcript.
  An agent can propose corrected or translated text, which must appear in review.
  Setting a language label alone does not translate the text.
- `delivery`: `clean`, `finished`, or `both`. Burned captions require finished or
  both; clean clips never have burned text.
- `playback_speed`: 0.5–2.0, default 1.0, with audio and caption retiming.
- `quality`: `fast`, `balanced`, or `quality`, controlling encoding effort rather
  than speech speed or editorial pace.

Times remain on the original source timeline even when playback speed changes.
Do not manually pre-adjust caption times. Reading-speed/timing failures need a
reviewed correction, not silent omission of words.

For transcription hints, pass them when starting transcription, for example
`clipear transcribe SOURCE_ID --language pt --glossary "BNB Chain, opBNB"`.
The edition's brief/glossary guides the agent; changing it does not re-run or
translate an existing transcript automatically.

```sh
clipear plan SOURCE_ID --file edition.json
clipear show-plan PLAN_ID
clipear preview PLAN_ID
clipear job JOB_ID
clipear review PLAN_ID
clipear render PLAN_ID
clipear job JOB_ID
```

To revise, use `clipear plan SOURCE_ID --file edition.json --plan-id PLAN_ID`.
Review and approve again. For transcript pagination and any additional options,
run `clipear transcript --help`; `clipear --help` lists the installed commands.

## Connect an MCP client

On macOS/Linux, use stdio when the agent client can start a local process. It does
not need an HTTP listener or a bearer token. On Windows, use a separately launched
authenticated HTTP server as described below.

Desktop apps usually do not inherit a virtual environment activated in your
terminal. Set the server's `command` to the absolute path of that environment's
Python executable, and put `-m clipear mcp --transport stdio` in its arguments.
Do not assume a bare `clipear` command is on the app's PATH.

Run `doctor` with the intended virtual environment's Python. Its `mcp_command`
array contains the matching executable followed by the arguments to start the
server; copy the first item into `command` and the remaining items into `args`.
The default transport is stdio. This avoids accidentally selecting another Python
installation.

For a terminal check on macOS/Linux, replace this example path:

```sh
"/absolute/path/to/clipear/.venv/bin/python" -m clipear mcp --transport stdio
```

For clients using a `mcpServers` JSON configuration, a macOS/Linux starting point is:

```json
{
  "mcpServers": {
    "clipear": {
      "command": "/absolute/path/to/clipear/.venv/bin/python",
      "args": ["-m", "clipear", "mcp", "--transport", "stdio"],
      "env": {
        "CLIPEAR_INPUT_ROOTS": "/absolute/path/to/camera-files",
        "CLIPEAR_WHISPER": "/absolute/path/to/whisper-cli",
        "CLIPEAR_MODEL": "/absolute/path/to/ggml-base.bin"
      }
    }
  }
}
```

These paths are placeholders; replace every one with a location on the processing
host. If you set `CLIPEAR_HOME`, use the same value for human CLI review. See also
[examples/mcp.json](../examples/mcp.json). Your client's format and settings
location may differ. Keep existing unrelated server settings intact.

The [official MCP local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
explains the client/server model. Consult your client's own current instructions;
this repository does not claim every native app has been connected and tested.
An agent needs the transcript tool, plan tools, and job polling; it does not get
an approval tool.

### Windows: use a separately launched HTTP server

The pinned SDK's Windows stdio client closes a kill-on-close Windows Job Object
when it disconnects. That can kill queued workers along with the stdio server.
Console/process-group detachment does not avoid this behavior; see Microsoft's
[Job Object lifetime documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
clipear therefore rejects import, transcription, preview, and render submissions
over Windows stdio, and `check_setup` reports the limitation. Reading existing
transcripts/jobs and creating/inspecting plans still work over stdio.

Start HTTP yourself in a separate PowerShell terminal, using the same input roots,
tools/model, and storage configured above. For example, from the clipear folder:

```powershell
$env:CLIPEAR_HTTP_TOKEN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:CLIPEAR_INPUT_ROOTS = "C:\path\to\camera-files"
.\.venv\Scripts\python.exe -m clipear mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Keep that terminal running while jobs process. Configure your MCP client's
Streamable HTTP connection to `http://127.0.0.1:8765/mcp` and its private bearer
authentication setting to the generated `CLIPEAR_HTTP_TOKEN` value. The request
header is `Authorization: Bearer <token>`. Client formats differ; use its documented
URL/authentication fields. A client that only supports stdio cannot submit Windows
background jobs through this MCP adapter; the regular CLI remains available.
Do not have the stdio client launch the HTTP host as its child, which would put
the host back under that client's process lifetime.

### Optional HTTP or remote worker

A long job can run on a computer you control while an MCP-capable client connects
from elsewhere. clipear provides the worker and authenticated Streamable HTTP
transport, not hosted infrastructure, an upload product, or provider-specific
deployment. Camera files must first be placed in an allowed folder on that host.

For local HTTP, set a strong unique token in the environment, then run:

```sh
clipear mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

The client must send `Authorization: Bearer <your token>`. Token storage belongs
in the host/client's secret settings, never the repository or shared example.
The HTTP server requires `CLIPEAR_HTTP_TOKEN`; see [security](security.md).

Keep the listener on loopback by default. Access from another host requires your
own authenticated network access and TLS termination, with the token protected
in transit. Binding a public address does not create TLS. Do not publish a raw
HTTP port. Use a client that supports this transport and its authentication.
Approval still happens through the processing host's interactive terminal or local
browser review; remote review requires a trusted way for the human to access that
host. There is no MCP endpoint for human approval.

For a host without automatic browser launch, `clipear review PLAN_ID --no-browser`
prints the local review URL. `--port PORT` chooses its loopback port, and
`--timeout SECONDS` controls its lifetime (1–3600 seconds; default 900). The human
must open that private link using trusted access to the host. Keep the command
running until approval or expiry, and do not share the review URL.

Poll `job JOB_ID` after starting import, transcription, preview, or render through
the CLI, macOS/Linux stdio, or a separately launched HTTP host. Their workers are
detached from the MCP connection and retain job state, but are not a
system service: shutdown, forced termination, missing executables, or unavailable
storage can still interrupt processing. Check the recorded error rather than
assuming a disconnected client means success.

## Troubleshooting

- **Camera file rejected:** inspect the actual path on the processing host and its
  configured input roots. Do not widen access to the whole disk as a workaround.
- **Transcription unavailable:** check both whisper.cpp and model paths with
  `doctor`, then run the upstream sample directly.
- **Burned captions unavailable:** inspect the FFmpeg build/filter capability.
  Install a build with libass or use a reviewed sidecar/clean plan.
- **YouTube download fails:** read the retained job error. YouTube, yt-dlp, and its
  JavaScript/runtime requirements can change. Consult
  [yt-dlp's upstream installation and troubleshooting guidance](https://github.com/yt-dlp/yt-dlp#installation).
  Do not silently bypass authentication, change the source, or upgrade a pinned
  package without checking the failure.
- **Approved render rejected:** inspect source fingerprint, plan revision/digest,
  and the home used by review. A changed plan needs fresh approval.
- **Command unavailable:** use the virtual environment's Python with `-m clipear`
  to avoid accidentally running a different installation.
- **Windows stdio rejects background work:** start the authenticated HTTP host
  separately and connect to its URL, as above. Do not retry the same submission
  through stdio or assume a queued job survived its client's process cleanup.

## Legacy Apple Silicon setup

`scripts/setup.sh` remains the original Mac-only path. It expects Homebrew,
installs FFmpeg/yt-dlp/CMake with it, builds whisper.cpp with Metal inside the
checkout, and downloads large-v3-turbo. It stops on Intel Mac, Windows, and Linux.
It is not the portable Python installer and is not needed for the workflow above.
Do not run it unless you explicitly choose that legacy setup.
