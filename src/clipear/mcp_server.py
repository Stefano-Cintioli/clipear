"""Small MCP adapter over the persisted engine, without approval capability.

The boundary prevents an MCP tool call from approving a plan. It does not
restrict a process with unrestricted access to the same operating-system account.
Machine settings are supplied by the host environment, never by tool arguments.
"""

from __future__ import annotations

import hmac
import inspect
import os
import re
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def create_server(service=None) -> MCPServer:
    """Build the SDK server; an injected service permits isolated protocol tests."""
    if service is None:
        from .config import Settings
        from .service import Service

        service = Service(Settings.from_env())

    server = MCPServer(
        "clipear", version="0.2.0", log_level="WARNING",
        instructions=(
            "Import a source, inspect its transcript, create an edit plan and preview it. "
            "A human reviews and approves the exact plan through the separate clipear CLI. "
            "No MCP tool can approve. Then render_approved_plan queues a persisted job. "
            "Poll get_job for long operations. Files must be accessible on this processing "
            "host and inside host-configured input roots. This tool boundary does not "
            "restrict unrestricted operating-system access."
        ),
    )
    allowed_arguments: dict[str, set[str]] = {}

    def register(*, read_only=False, open_world=False):
        def decorate(function):
            allowed_arguments[function.__name__] = set(inspect.signature(function).parameters)
            server.add_tool(function, annotations=ToolAnnotations(
                read_only_hint=read_only, destructive_hint=False,
                open_world_hint=open_world,
            ))
            return function
        return decorate

    def invoke(method: str, **arguments) -> dict:
        try:
            return getattr(service, method)(**arguments)
        except (ValueError, PermissionError, FileNotFoundError, RuntimeError) as error:
            # The SDK deliberately hides unexpected exceptions. Expected engine
            # validation errors must remain actionable for the connected agent.
            raise ToolError(str(error)) from error

    @register(read_only=True)
    def check_setup() -> dict[str, Any]:
        """Check host dependencies and configuration without changing machine settings."""
        return invoke("check_setup")

    @register(open_world=True)
    def import_source(source: str) -> dict[str, Any]:
        """Queue one YouTube URL or camera file within the host's allowed input roots."""
        return invoke("import_source", source=source)

    @register()
    def transcribe_source(source_id: str, language: str = "auto", glossary: str = "") -> dict[str, Any]:
        """Queue host-local transcription. Returns a job_id; poll get_job for completion."""
        return invoke("transcribe_source", source_id=source_id, language=language, glossary=glossary)

    @register(read_only=True)
    def get_transcript(source_id: str, offset: int = 0, limit: int = 200) -> dict[str, Any]:
        """Read a page of source-timeline transcript segments from a registered source."""
        return invoke("get_transcript", source_id=source_id, offset=offset, limit=limit)

    @register()
    def create_edit_plan(
        source_id: str, clips: list[dict[str, Any]],
        brief: dict[str, Any] | None = None, outputs: list[dict[str, Any]] | None = None,
        captions: dict[str, Any] | None = None, delivery: str = "clean",
        playback_speed: float = 1.0, quality: str = "balanced", plan_id: str | None = None,
    ) -> dict[str, Any]:
        """Create/revise a plan. Revisions require separate human approval before render.

        clips contain id/title/start/end. outputs select name/ratio/height/fit/position.
        captions contain mode/language and optional source-timeline cues. brief supplies
        editorial context; it does not make the engine choose or translate highlights.
        """
        return invoke("create_edit_plan", source_id=source_id, clips=clips, brief=brief,
                      outputs=outputs, captions=captions, delivery=delivery,
                      playback_speed=playback_speed, quality=quality, plan_id=plan_id)

    @register(read_only=True)
    def get_edit_plan(plan_id: str) -> dict[str, Any]:
        """Inspect the exact plan revision, digest and current human approval status."""
        return invoke("get_edit_plan", plan_id=plan_id)

    @register()
    def preview_edit_plan(plan_id: str) -> dict[str, Any]:
        """Queue framing stills for human review; returns the persisted job_id."""
        return invoke("preview_edit_plan", plan_id=plan_id)

    @register()
    def render_approved_plan(plan_id: str) -> dict[str, Any]:
        """Queue a render of an already human-approved exact plan revision and source.

        This tool cannot grant approval. An unapproved or changed plan fails visibly.
        """
        return invoke("render_approved_plan", plan_id=plan_id)

    @register(read_only=True)
    def get_job(job_id: str) -> dict[str, Any]:
        """Read persisted job progress/results/errors, including after a disconnect."""
        return invoke("get_job", job_id=job_id)

    async def reject_unknown_arguments(context, call_next):
        if context.method == "tools/call" and context.params:
            name = context.params.get("name")
            arguments = context.params.get("arguments", {})
            if name in allowed_arguments and isinstance(arguments, dict):
                unknown = set(arguments) - allowed_arguments[name]
                if unknown:
                    return CallToolResult(is_error=True, content=[TextContent(
                        type="text", text="Unknown tool arguments: " + ", ".join(sorted(unknown)))])
        return await call_next(context)

    # SDK argument models otherwise ignore unknown keys. Reject them before
    # dispatch so model-supplied approval/configuration flags fail explicitly.
    server.middleware.append(reject_unknown_arguments)
    return server


class _BearerAuth:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self._token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            values = [value for key, value in scope.get("headers", [])
                      if key.lower() == b"authorization"]
            candidate = b""
            if len(values) == 1 and values[0][:7].lower() == b"bearer ":
                candidate = values[0][7:]
            if not hmac.compare_digest(candidate, self._token):
                await JSONResponse({"error": "Bearer authentication required"}, status_code=401,
                                   headers={"WWW-Authenticate": 'Bearer realm="clipear"'})(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_http_app(service=None, *, token: str | None = None, host: str = "127.0.0.1") -> ASGIApp:
    """Return authenticated SDK Streamable HTTP at /mcp, with no CORS middleware.

    Every HTTP binding requires a host-configured bearer token. Remote access also
    requires the operator's TLS/network configuration; this adapter is single-user.
    """
    secret = os.environ.get("CLIPEAR_HTTP_TOKEN") if token is None else token
    if not secret or re.fullmatch(r"[A-Za-z0-9\-._~+/]+=*", secret) is None:
        raise ValueError("Set CLIPEAR_HTTP_TOKEN to a nonempty bearer token before starting HTTP")
    app = create_server(service).streamable_http_app(host=host, json_response=True)
    return _BearerAuth(app, secret)


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start stdio (default) or authenticated Streamable HTTP using host settings."""
    if transport == "stdio":
        create_server().run(transport="stdio")
    elif transport == "streamable-http":
        import uvicorn

        uvicorn.run(create_http_app(host=host), host=host, port=port,
                    log_level="warning", access_log=False)
    else:
        raise ValueError("transport must be stdio or streamable-http")


if __name__ == "__main__":
    run_server()
