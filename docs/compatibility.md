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

**Current native status:** no CI run is claimed by this document. Record local
end-to-end evidence and actual CI results with host, Python, FFmpeg, and whisper.cpp
versions before broadening that claim. Windows ARM and Linux ARM are not in this
matrix. Upstream tool availability on an architecture does not prove clipear was
tested there.

## Processing tools

- Python 3.11+ is required; CI currently exercises 3.11/3.12.
- FFmpeg and ffprobe are external. The common output baseline is software H.264
  with square pixels, yuv420p, and AAC when input audio exists.
- Finished burned captions need an FFmpeg build with libass/ASS support. A clean
  export does not prove that capability works. `doctor` reports it.
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
