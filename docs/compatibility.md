# Compatibility and verification status

The Python engine targets macOS on Apple Silicon and Intel, Windows, and Linux.
This describes the intended interfaces and validation scope. A platform is only
called tested when an actual run is recorded.

## Platform coverage

The [CI workflow](../.github/workflows/test.yml) defines Python 3.11 and 3.12 jobs
for:

- Ubuntu 24.04, x64.
- Windows Server 2022, x64.
- macOS 15, Intel (`macos-15-intel`).
- macOS 15, Apple Silicon (`macos-15`).

The labels follow GitHub's [hosted runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Those jobs install FFmpeg, require it to be discoverable, install clipear in an
isolated virtual environment, and run standard-library unit tests, including
actual media fixtures. A workflow file alone does not show that these runs passed.
Before tests, CI checks the actual `subtitles` filter and `libx264` encoder, rather
than accepting a version check. Mac runners retain a preinstalled build only if
both features exist; the Apple Silicon fallback is Homebrew's keg-only
[`ffmpeg-full` bottle](https://formulae.brew.sh/formula/ffmpeg-full), with its bin
folder explicitly added to the job's PATH. Its [formula](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/f/ffmpeg-full.rb)
enables libass and libx264. Current full-formula bottles do not cover Intel Mac;
the Intel fallback uses [Evermeet's FFmpeg/ffprobe 9.0.2 static releases](https://evermeet.cx/ffmpeg/),
the third-party macOS provider linked by [FFmpeg's download page](https://ffmpeg.org/download.html).
The workflow pins both ZIP archive hashes before extraction. Their detached
signatures were checked against Evermeet's published signing-key fingerprint
`20F6EA3E0CFD6B4C53447A73476C4B611A660874` when selecting the artifacts. Neither
fallback compiles FFmpeg from source, and finished-caption tests remain enabled.

**Native results:** inspect the latest commit's [pull request checks](https://github.com/Stefano-Cintioli/clipear/pull/1/checks)
and [main-branch runs](https://github.com/Stefano-Cintioli/clipear/actions/workflows/test.yml).
Each job records the host, Python and FFmpeg versions and its actual test result.
Local speech-model and browser checks are recorded in [verification](verification.md).
Windows ARM and Linux ARM are not in this matrix. Upstream tool availability on
an architecture does not prove clipear was tested there.

## Processing tools

- Python 3.11+ is required; CI currently exercises 3.11/3.12.
- FFmpeg and ffprobe are external. The common output baseline is software H.264
  with square pixels, yuv420p, and AAC when input audio exists.
- Finished burned captions need an FFmpeg build with libass and the `subtitles`
  filter. `doctor` reports ASS-filter support; CI checks `subtitles` specifically.
  Verify an actual finished export, since a clean export does not exercise captions.
- whisper.cpp and its model are external. The engine calls the configured
  executable; CPU works as the baseline. Metal/CUDA/Vulkan depend on the chosen
  upstream build and hardware and are not a clipear speed guarantee.
- CI does not download a speech model or claim a real whisper transcription.
  Verify an actual model/sample separately. Media tests may skip locally when
  FFmpeg is absent; the CI dependency check is intended to prevent that omission
  on its runners.

## Bundled caption font

Finished captions use the bundled, unmodified **Inter Bold 4.1** from the
[official Inter v4.1 release](https://github.com/rsms/inter/releases/tag/v4.1).
The font retains its SIL Open Font License 1.1; clipear's MIT license does not
replace the font's license. The full copyright notice and license are included in
[assets/fonts/LICENSE.txt](../src/clipear/assets/fonts/LICENSE.txt), corresponding
to the [upstream tagged license](https://github.com/rsms/inter/blob/v4.1/LICENSE.txt).

Local bundled-file SHA-256 identifiers:

- `Inter-Bold.ttf`: `288316099b1e0a47a4716d159098005eef7c0066921f34e3200393dbdb01947f`
- `LICENSE.txt`: `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a`

The package includes this font so caption appearance does not depend on a user
having Inter installed system-wide. FFmpeg still needs working libass/font
support; a bundled font alone does not prove a finished export works.

## Sources and outputs

Supported new-workflow inputs are a YouTube URL or a local media file readable
by the installed FFmpeg build. Camera MOV/MP4 containers and unusual codecs depend
on that build; verify the actual file rather than assuming a camera-brand matrix.
There is no X/Twitter support claim in the Python workflow. YouTube extraction is
subject to upstream/site changes and may require additional runtime capabilities.

Outputs are clean MP4, optional SRT sidecars, or finished MP4 with burned captions.
Choose source/16:9/9:16/1:1/4:5 framing, padding or a fixed crop. Preview stills
help assess the crop; there is no speaker/face tracking or automatic reframing.
The supported playback-speed range is 0.5–2.0, with audio/subtitle retiming.
These are standard files for an editor, not a native CapCut/Premiere project.

## MCP and remote hosts

The server offers stdio and authenticated Streamable HTTP. Protocol tests should
cover actual initialization, tool discovery/calls, authorization failures, and
the absence of an approval tool. Successful protocol tests do not establish a
tested native-app integration.

### Windows MCP lifetime

Windows background processing uses a separately launched authenticated HTTP host.
The pinned SDK's stdio client assigns its server to a kill-on-close Windows Job
Object and closes that object on disconnect, terminating descendant workers too.
Windows console/process-group detachment does not remove this association; see
[Microsoft's Job Object documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

clipear's Windows stdio server reports `background_jobs_supported: false` in
`check_setup` and rejects import, transcription, preview, and render submissions
with instructions to use HTTP. It still permits setup, transcript/job reads,
and plan creation/inspection. This is an explicit transport limitation, not a
claim that Windows stdio jobs survive disconnect.

The production integration test checks actual Windows stdio rejection and a
separate HTTP host's import, plan, human-approval boundary, render, and reconnect
workflow over real SDK network connections. On macOS/Linux, it additionally runs
that workflow over real CLI stdio connections. It joins HTTP worker observer
threads before removing temporary files, and includes job state, audit events,
and retained log tails in a failure. Native test results must still be recorded
before claiming a specific platform/version passed. See the
[Windows connection instructions](setup.md#windows-use-a-separately-launched-http-server).

No native Claude Desktop, Claude Code, Codex, ChatGPT, or Grok connection is
claimed here without a recorded client/version/run. Clients vary in support for
stdio, remote HTTP, authentication, and local file access. Follow current client
documentation and keep clipear's separate human approval step.

A remote worker is an installation on a host you operate, with host-accessible
input files, storage, tools, network/TLS configuration, and human review access.
No hosted public product, automatic provisioning, provider deployment template,
or automatic client-to-worker file upload is included.

## Legacy workflow

The existing Bash scripts are retained for the original Apple Silicon setup.
`scripts/setup.sh` explicitly rejects other systems and builds whisper.cpp with
Metal. Legacy `cut.sh` uses stream copy by default, so cuts are limited by keyframes;
the Python engine re-encodes approved ranges.

Legacy commands, environment files, glossary behavior, and output folders do not
automatically configure the Python engine. Use the documented `CLIPEAR_*` host
settings for it. The Python engine tracks source/plan/job IDs and does not require
a new chat for each video. Keep legacy and portable results distinct when reporting
what was tested.
