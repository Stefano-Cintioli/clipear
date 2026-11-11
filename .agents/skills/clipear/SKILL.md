---
name: clipear
description: Use clipear to import a YouTube video or local camera file, inspect its transcript, propose an edition, obtain separate human approval, and render clean or finished captioned clips.
---

# clipear

Read repository-root [AGENTS.md](../../../AGENTS.md) before processing a video.
It contains the shared workflow, verification requirements, and human approval
boundary. For first-time setup, use [docs/setup.md](../../../docs/setup.md).
For the edition format and CLI, use [README.md](../../../README.md) and
[examples/edition.json](../../../examples/edition.json).

Use the installed Python CLI or the connected clipear MCP tools. Identify the
processing host and existing source/plan/job IDs before reusing them. The agent
may propose a plan and request an already approved render. The human performs
approval in the separate terminal or local browser; never automate that step.
