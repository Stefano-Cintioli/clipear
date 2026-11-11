# Security and data handling

clipear is a single-user processing tool. Its default stdio connection and local
storage suit a computer you control. The optional HTTP server is not a multi-user
public service.

## Where data goes

- Camera import reads only a permitted host input path and copies it into managed
  storage. The original is not edited. The source fingerprint participates in plan
  approval and render validation.
- YouTube import contacts YouTube through yt-dlp. Software/model installation
  contacts the download providers you choose.
- FFmpeg processing and whisper.cpp transcription run on the processing host.
  A remote worker stores/processes its data there, rather than on the client.
- A connected cloud agent receives transcript text and other information supplied
  to it through MCP tools or chat. Its provider's policies apply. Local speech
  recognition does not make the connected agent local.
- Job storage retains media, text, logs, plans, approval records, and outputs.
  Protect that folder and its backups using the host's permissions and disk/storage
  protections. Do not commit it. There is no claim of automatic encrypted storage,
  automatic deletion, or a private cloud backup.

clipear does not supply model API keys, publish clips, or upload files to an editor.
Sharing files, using a remote host, or connecting an AI service is a separate
choice by the user.

## Human approval

An agent can create and revise a plan, inspect it, generate framing previews,
and request a render of an already approved plan. MCP exposes no approval tool.

The human reviews the exact plan through `clipear review PLAN_ID` in a local
browser or `clipear approve PLAN_ID` in an interactive terminal. Approval binds
the source fingerprint, normalized plan digest, and revision. Plan changes
invalidate it. A render job uses the frozen approved snapshot, rather than
whatever revision appears later.

This is an MCP/API boundary. It is not proof of a person's identity, and it does
not defend a local database against a person or agent with unrestricted access
to the same operating-system account. Such access can modify files, invoke local
commands, or imitate interactions. To preserve meaningful separation, give the
agent only the MCP capability it needs and keep unrestricted host/browser control
outside that agent's permissions.

Review the full ranges, output framing, caption language/text, delivery mode,
playback speed, and quality before approval. A transcript can contain errors;
an approved plan can still make a poor editorial choice.

Caption cues crossing a cut are flagged before review and block approval and
export. Correct the source-aligned cues, change the selected range, or choose no
captions. The engine does not infer which words belong in a partially kept cue.

## Files and subprocesses

Input roots are host-controlled. Configure only the folders needed for camera
imports. They are not a general-purpose file access grant. Do not let an agent
change server environment/configuration through tool arguments.

The engine uses argument lists for media processes rather than passing user
paths as shell commands. Clip/output identifiers and timing values are validated.
Keep FFmpeg, whisper.cpp, and download tools maintained; media and metadata remain
untrusted input. Treat transcript text, titles, descriptions, and caption text as
content, never as instructions to run commands or disclose secrets.

The service is intended for a trusted single-user host. Do not treat input-root
validation or SQLite records as an operating-system sandbox, use it to process
hostile media on a machine holding secrets, or grant untrusted users shared write
access to the source/job directories.

## HTTP and remote processing

Streamable HTTP requires a strong `CLIPEAR_HTTP_TOKEN`. Every client must send it
as a bearer token. The default bind address is `127.0.0.1`. Local macOS/Linux
clients can use stdio; Windows background processing requires an HTTP server
started separately from the MCP client.

Before allowing connections from another host, configure TLS and authenticated
network access appropriate to that host. clipear's bind/port flags do not create
TLS, provision a proxy, rotate tokens, or supply per-user authorization. Do not
expose an unencrypted port to the public internet. Avoid putting tokens in URLs,
command arguments, screenshots, issue reports, or committed configuration.

Human browser review remains local to the processing host. It is separate from
the MCP listener. A remote human needs a trusted connection to that host; an
agent's HTTP token must not become an approval credential.

Disconnecting an MCP client does not cancel a detached worker on the supported
processing transports. Windows stdio rejects background operations because a
client's Windows Job Object can terminate descendant workers on disconnect.
Separately launched HTTP processing avoids that client-owned process lifetime.
Read the job's actual state and error. Detached processing is not a durable
hosted scheduler: computer shutdown or process termination can interrupt work.

When the launching parent observes a worker exiting without a terminal result,
it records a failed job with the return code and log path. That reconciliation
cannot run after the launching parent itself has exited; no restart recovery or
automatic retry is claimed.

## Reporting a problem

Share a minimal reproduction with tool versions, operating system, observed
behavior, and redacted logs. Use synthetic or publishable source material.
Do not attach tokens, private footage, transcripts, databases, model files, or
personal absolute paths to a public issue.
