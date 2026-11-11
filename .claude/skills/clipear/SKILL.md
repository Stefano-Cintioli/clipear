---
name: clipear
description: Process a YouTube video or local camera file with clipear, propose an edit plan, wait for separate human approval, and export clean MP4/SRT or finished captioned clips. Use for the clipear repository workflow; setup has its own skill.
disable-model-invocation: true
---

# clipear

Read the repository-root [AGENTS.md](../../../AGENTS.md) and follow its canonical
video workflow and approval boundary. Read [README.md](../../../README.md) for the
CLI flow and [docs/setup.md](../../../docs/setup.md) if tools are missing.

`$ARGUMENTS` identifies a YouTube source, local file, or existing source/plan/job.
Confirm which one it is before reusing state. Use the installed Python CLI or
clipear MCP tools. The agent proposes; the human approves through the separate
interactive terminal or local browser. Never simulate that approval.

These are project-scoped instructions. If copying this skill elsewhere, preserve
access to the repository and its canonical documents; do not install it globally
without the user's request.
