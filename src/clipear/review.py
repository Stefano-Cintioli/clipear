"""Loopback-only human review. This approval route is never an MCP tool."""
from __future__ import annotations

import copy
import hashlib
import hmac
import html
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .captions import caption_warnings


def create_review_server(service, plan_id: str, *, port: int = 0, previews: list[dict] | None = None, preview_error: str | None = None, plan_snapshot: dict | None = None):
    # A review with previews must use the same revision that generated them.
    # Approval still checks that revision against current storage atomically.
    plan = copy.deepcopy(plan_snapshot if plan_snapshot is not None else service.get_edit_plan(plan_id))
    if plan["id"] != plan_id:
        raise ValueError("Review snapshot belongs to another plan")
    warnings = caption_warnings(plan["document"])
    caption_conflicts = any(warning["code"] == "boundary_conflict" for warning in warnings)
    service._verified_source(plan["source_id"])
    nonce = secrets.token_urlsafe(32)
    path = "/review/" + nonce
    completed = threading.Event()
    safe_previews = {}
    for index, item in enumerate(previews or []):
        file = Path(item["path"]).resolve()
        if not file.is_relative_to(service.settings.home.resolve()) or not file.is_file() or file.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        safe_previews[f"{path}/frame/{index}"] = (file, item)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Approval nonce must not enter HTTP logs.

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def respond(self, status: int, body: str | bytes, content_type: str = "text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, "Invalid local host")
            route = urllib.parse.urlsplit(self.path).path
            if route in safe_previews:
                file, item = safe_previews[route]
                return self.respond(200, file.read_bytes(), "image/png" if file.suffix == ".png" else "image/jpeg")
            if not hmac.compare_digest(route, path):
                return self.respond(404, "Review not found")
            doc = plan["document"]
            esc = html.escape
            cards = "".join(f'<figure><img src="{esc(key)}" alt="{esc(str(item["clip"]))} / {esc(str(item["profile"]))}"><figcaption>{esc(str(item["clip"]))} · {esc(str(item["profile"]))}</figcaption></figure>' for key, (_, item) in safe_previews.items())
            notice = "" if cards else '<p class="notice">No framing stills are available. Run preview and check framing before approving crop settings.</p>'
            if preview_error:
                notice += f'<p class="notice">Preview error: {esc(preview_error)}</p>'
            warning_panel = ""
            if warnings:
                blocked = '<p class="notice">Approval is blocked until caption boundary conflicts are resolved. Provide corrected source-aligned cues, choose a different clip, or set captions mode to none, then review the revised plan.</p>' if caption_conflicts else ""
                warning_panel = f'<section class="panel"><h2>Caption warnings</h2>{blocked}<pre>{esc(json.dumps(warnings, ensure_ascii=False, indent=2))}</pre></section>'
            disabled = " disabled" if caption_conflicts else ""
            clips = "".join(f'<li><strong>{esc(c["title"])}</strong> <span>{c["start"]:.3f}–{c["end"]:.3f}s</span></li>' for c in doc["clips"])
            page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review this edition · clipear</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;margin:0;background:#f4f4f1;color:#1c2421}}main{{max-width:1040px;margin:auto;padding:32px 24px}}h1{{font-size:32px;margin-bottom:8px}}small,.muted{{color:#52615b}}.panel{{background:white;border:1px solid #d9dfdb;padding:24px;border-radius:12px;margin:20px 0}}.frames{{display:flex;flex-wrap:wrap;gap:16px}}figure{{margin:0;max-width:320px}}img{{max-width:100%;max-height:320px;display:block}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}}button{{background:#195c42;color:white;border:0;border-radius:8px;padding:14px 20px;font:inherit;cursor:pointer}}li{{padding:5px 0}}li span{{white-space:nowrap;margin-left:12px}}label{{display:block;margin-bottom:16px}}.notice{{color:#824915}}summary{{cursor:pointer;font-weight:600}}</style>
<main><small>CLIPEAR · HUMAN REVIEW</small><h1>Review this edition</h1><p>Approve the clips, framing, captions and playback speed shown here. This records approval; it does not start a render.</p>
<section class="panel"><h2>{esc(str(doc.get("brief", {}).get("goal", "Selected clips")))}</h2><ul>{clips}</ul><p>Delivery: <strong>{esc(doc["delivery"])}</strong> · Playback: <strong>{doc["playback_speed"]}×</strong> · Quality: <strong>{esc(doc["quality"])}</strong> · Captions: <strong>{esc(doc["captions"]["mode"])}</strong></p></section>
<section class="panel"><h2>Framing previews</h2>{notice}<div class="frames">{cards}</div></section>
{warning_panel}
<section class="panel"><details open><summary>Full plan, including caption text and editorial brief</summary><pre>{esc(json.dumps(doc, ensure_ascii=False, indent=2))}</pre></details></section>
<section class="panel"><p class="muted">Revision {plan["revision"]} · Plan {esc(plan_id)} · Fingerprint {esc(plan["digest"][:12])}. Any revision invalidates this approval.</p>
<form method="post" action="{esc(path)}"><input type="hidden" name="digest" value="{esc(plan["digest"])}"><label><input type="checkbox" name="confirm" value="yes" required{disabled}> I reviewed this exact plan and approve these edits and export settings.</label><button type="submit"{disabled}>Approve this revision</button></form></section></main></html>'''
            self.respond(200, page)

        def do_POST(self):
            expected_origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.valid_host() or self.headers.get("Origin") not in {expected_origin, f"http://localhost:{self.server.server_port}"}:
                return self.respond(403, "Approval requires the same local review page")
            if not hmac.compare_digest(urllib.parse.urlsplit(self.path).path, path):
                return self.respond(404, "Review not found")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.respond(400, "Invalid request length")
            if not 0 < length <= 4096 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
                return self.respond(400, "Invalid confirmation form")
            values = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", errors="strict"))
            if completed.is_set() or values.get("confirm") != ["yes"] or values.get("digest") != [plan["digest"]]:
                return self.respond(400, "Explicit confirmation of the displayed revision is required")
            try:
                service._verified_source(plan["source_id"])
                service.store.approve(plan_id, plan["digest"], plan["revision"])
            except (PermissionError, ValueError, FileNotFoundError) as error:
                return self.respond(409, html.escape(str(error)))
            completed.set()
            self.respond(200, "<h1>Revision approved</h1><p>You can close this page. Your agent can now render this exact plan.</p>")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, f"http://127.0.0.1:{server.server_port}{path}", completed


def run_review(service, plan_id: str, *, port: int = 0, open_browser: bool = True, timeout: int = 900) -> dict:
    if not 1 <= timeout <= 3600 or not 0 <= port <= 65535:
        raise ValueError("Review timeout must be 1..3600 seconds and port 0..65535")
    plan = service.get_edit_plan(plan_id)
    source = service._verified_source(plan["source_id"])
    directory = service.settings.home / "reviews" / plan_id / plan["digest"]
    previews, error = [], None
    try:
        previews = service._media().preview(Path(source["path"]), directory, plan["document"])
    except (RuntimeError, ValueError, OSError) as problem:
        error = str(problem)
    server, url, completed = create_review_server(service, plan_id, port=port, previews=previews, preview_error=error, plan_snapshot=plan)
    server.timeout = 1
    print(f"Open this private local review link in your browser:\n{url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    deadline = time.monotonic() + timeout
    with server:
        while not completed.is_set() and time.monotonic() < deadline:
            server.handle_request()
    return {"plan_id": plan_id, "approved": completed.is_set(), "digest": plan["digest"], "revision": plan["revision"], "message": "Approved" if completed.is_set() else "Review expired without approval"}
