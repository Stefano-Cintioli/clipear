"""Human commands and JSON CLI fallback for the shared engine."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Settings
from .captions import require_caption_boundaries
from .service import Service


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipear", description="Portable video clipping with human-approved edit plans")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--home", help="Private job storage; also configurable with CLIPEAR_HOME")
    p.add_argument("--input-root", action="append", help="Allowed camera-file directory; repeat for more than one")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check tools/model and report capabilities without installing anything")
    imp = sub.add_parser("import", help="Copy a camera file or download one YouTube video in a background job")
    imp.add_argument("source")
    tr = sub.add_parser("transcribe", help="Transcribe an imported source on the processing host")
    tr.add_argument("source_id"); tr.add_argument("--language", default="auto"); tr.add_argument("--glossary", default="")
    transcript = sub.add_parser("transcript", help="Read a compact transcript page")
    transcript.add_argument("source_id"); transcript.add_argument("--offset", type=int, default=0); transcript.add_argument("--limit", type=int, default=200)
    plan = sub.add_parser("plan", help="Create/revise an edition plan from a JSON file")
    plan.add_argument("source_id"); plan.add_argument("--file", required=True); plan.add_argument("--plan-id")
    for command, label in [("show-plan", "Read the exact current plan"), ("preview", "Generate framing stills as a job"), ("approve", "Human-only interactive terminal approval"), ("review", "Human-only local browser review"), ("render", "Queue an already approved exact plan")]:
        s = sub.add_parser(command, help=label); s.add_argument("plan_id")
        if command == "review":
            s.add_argument("--port", type=int, default=0); s.add_argument("--no-browser", action="store_true"); s.add_argument("--timeout", type=int, default=900)
    job = sub.add_parser("job", help="Read persisted job progress/results/errors")
    job.add_argument("job_id")
    mcp = sub.add_parser("mcp", help="Run the MCP server; stdout is the stdio protocol")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--host", default="127.0.0.1"); mcp.add_argument("--port", type=int, default=8765)
    return p


def approve_interactively(service: Service, plan_id: str) -> dict:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise PermissionError("Approval requires a person in an interactive terminal, or use clipear review PLAN_ID; stdin/--yes cannot approve")
    plan = service.get_edit_plan(plan_id)
    service._verified_source(plan["source_id"])
    print(json.dumps(plan["document"], ensure_ascii=False, indent=2))
    if plan["warnings"]:
        print("Caption warnings:")
        print(json.dumps(plan["warnings"], ensure_ascii=False, indent=2))
    require_caption_boundaries(plan["document"])
    phrase = f"APPROVE {plan['digest'][:12]}"
    response = input(f"Review the ranges, framing, captions and speed above. Type {phrase} to approve this exact revision: ")
    if response != phrase:
        raise PermissionError("No approval recorded")
    service.store.approve(plan_id, plan["digest"], plan["revision"])
    return {"plan_id": plan_id, "digest": plan["digest"], "approved": True}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = Settings.from_env(args.home)
        if args.input_root:
            settings = replace(settings, input_roots=tuple(Path(p).expanduser().resolve() for p in args.input_root))
        if args.command == "mcp":
            # Per-process launch settings, not user/global configuration changes.
            os.environ["CLIPEAR_HOME"] = str(settings.home)
            os.environ["CLIPEAR_INPUT_ROOTS"] = os.pathsep.join(str(p) for p in settings.input_roots)
            from .mcp_server import run_server
            run_server(args.transport, args.host, args.port)
            return 0
        service = Service(settings)
        if args.command == "doctor":
            result = service.check_setup()
        elif args.command == "import":
            result = service.import_source(args.source)
        elif args.command == "transcribe":
            result = service.transcribe_source(args.source_id, args.language, args.glossary)
        elif args.command == "transcript":
            result = service.get_transcript(args.source_id, args.offset, args.limit)
        elif args.command == "plan":
            with Path(args.file).open(encoding="utf-8") as stream:
                edition = json.load(stream)
            if not isinstance(edition, dict):
                raise ValueError("Edition file must be a JSON object")
            allowed = {"clips", "brief", "outputs", "captions", "delivery", "playback_speed", "quality"}
            if set(edition) - allowed:
                raise ValueError("Unknown edition fields: " + ", ".join(sorted(set(edition)-allowed)))
            result = service.create_edit_plan(args.source_id, plan_id=args.plan_id, **edition)
        elif args.command == "show-plan":
            result = service.get_edit_plan(args.plan_id)
        elif args.command == "preview":
            result = service.preview_edit_plan(args.plan_id)
        elif args.command == "approve":
            result = approve_interactively(service, args.plan_id)
        elif args.command == "review":
            from .review import run_review
            result = run_review(service, args.plan_id, port=args.port, open_browser=not args.no_browser, timeout=args.timeout)
        elif args.command == "render":
            result = service.render_approved_plan(args.plan_id)
        elif args.command == "job":
            result = service.get_job(args.job_id)
        else:
            raise ValueError("Unsupported command")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, PermissionError, FileNotFoundError, RuntimeError, OSError) as error:
        print(f"clipear error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped. Background jobs already submitted retain their status.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
