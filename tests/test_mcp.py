"""Exercise clipear's MCP boundary through the pinned official SDK."""

import asyncio
from functools import wraps
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
import uvicorn


class FakeService:
    """Only the engine is replaced; SDK dispatch and transports remain real."""

    def check_setup(self):
        return {"ready": True, "engine": "test-fixture"}

    def import_source(self, source):
        if source != "https://www.youtube.com/watch?v=fixture":
            raise ValueError("source is outside configured input roots")
        return {"job_id": "ingest-123", "status": "queued"}

    def transcribe_source(self, source_id, language="auto", glossary=""):
        return {"job_id": "transcribe-123", "status": "queued"}

    def get_transcript(self, source_id, offset=0, limit=200):
        if offset < 0 or limit < 1:
            raise ValueError("offset must be nonnegative and limit positive")
        return {"source_id": source_id, "language": "es", "segments": [
            {"start": 0, "end": 1, "text": "Hola"}], "offset": offset,
            "total": 1, "next_offset": None}

    def create_edit_plan(self, source_id, clips, brief=None, outputs=None,
                         captions=None, delivery="clean", playback_speed=1.0,
                         quality="balanced", plan_id=None):
        return {"id": plan_id or "plan-123", "revision": 1, "digest": "abc",
                "approved": False, "document": {"source_id": source_id,
                "clips": clips, "brief": brief, "outputs": outputs,
                "captions": captions, "delivery": delivery,
                "playback_speed": playback_speed, "quality": quality},
                "approval_instructions": "A human must review this plan in the CLI."}

    def get_edit_plan(self, plan_id):
        return {"id": plan_id, "revision": 1, "digest": "abc", "approved": False,
                "document": {"source_id": "source-123", "clips": []}}

    def preview_edit_plan(self, plan_id):
        return {"job_id": "preview-123", "status": "queued"}

    def render_approved_plan(self, plan_id):
        raise PermissionError("Human approval is required for the exact plan revision")

    def get_job(self, job_id):
        return {"id": job_id, "kind": "import", "status": "queued",
                "progress": 0, "message": "Queued", "result": None,
                "error": None, "created_at": "2026-11-11T00:00:00Z",
                "updated_at": "2026-11-11T00:00:00Z"}

    def approve_plan(self, plan_id):
        raise AssertionError("This engine method must never be exposed through MCP")


def error_text(result):
    return " ".join(item.text for item in result.content if hasattr(item, "text"))


def with_client(test):
    @wraps(test)
    async def run(self):
        from clipear.mcp_server import create_server
        async with Client(create_server(FakeService(), transport="embedded"), mode="legacy") as client:
            self.client = client
            await test(self)
    return run


class MCPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_stdio_reports_and_rejects_background_work(self):
        from clipear.mcp_server import create_server
        with patch("sys.platform", "win32"):
            server = create_server(FakeService(), transport="stdio")
        async with Client(server, mode="legacy") as client:
            setup = await client.call_tool("check_setup")
            self.assertFalse(setup.structured_content["mcp_transport"]["background_jobs_supported"])
            self.assertIn("separately", setup.structured_content["mcp_transport"]["limitation"])
            for name, arguments in [
                ("import_source", {"source": "https://www.youtube.com/watch?v=fixture"}),
                ("transcribe_source", {"source_id": "source-123"}),
                ("preview_edit_plan", {"plan_id": "plan-123"}),
                ("render_approved_plan", {"plan_id": "plan-123"}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertTrue(result.is_error)
                self.assertIn("streamable-http", error_text(result))
                self.assertIn("separately", error_text(result))
            plan = await client.call_tool("get_edit_plan", {"plan_id": "plan-123"})
            self.assertFalse(plan.is_error)

    @with_client
    async def test_only_small_engine_surface_and_no_machine_or_approval_inputs(self):
        tools = (await self.client.list_tools()).tools
        self.assertEqual({tool.name for tool in tools}, {
            "check_setup", "import_source", "transcribe_source", "get_transcript",
            "create_edit_plan", "get_edit_plan", "preview_edit_plan",
            "render_approved_plan", "get_job"})
        for tool in tools:
            self.assertFalse({"home", "input_roots", "executable", "approved",
                              "approve", "token"} & set(tool.input_schema["properties"]))
        denied = await self.client.call_tool("approve_plan", {"plan_id": "plan-123"})
        self.assertTrue(denied.is_error)

    @with_client
    async def test_engine_validation_and_unapproved_render_stay_visible(self):
        denied = await self.client.call_tool("render_approved_plan", {"plan_id": "plan-123"})
        self.assertTrue(denied.is_error)
        self.assertIn("Human approval", error_text(denied))
        invalid = await self.client.call_tool("import_source", {"source": "/etc/passwd"})
        self.assertTrue(invalid.is_error)
        self.assertIn("input roots", error_text(invalid))
        missing = await self.client.call_tool("get_job", {})
        self.assertTrue(missing.is_error)
        healthy = await self.client.call_tool("check_setup", {})
        self.assertFalse(healthy.is_error)
        self.assertEqual(healthy.structured_content["ready"], True)

    @with_client
    async def test_approval_and_machine_configuration_cannot_be_injected(self):
        for tool, arguments in [
            ("check_setup", {"home": "/tmp/alternate"}),
            ("render_approved_plan", {"plan_id": "plan-123", "approved": True}),
            ("create_edit_plan", {"source_id": "source-123", "clips": [], "approve": True}),
        ]:
            result = await self.client.call_tool(tool, arguments)
            self.assertTrue(result.is_error, tool)
            self.assertIn("Unknown", error_text(result))

    @with_client
    async def test_job_tools_return_engine_job_ids_and_plan_fields_round_trip(self):
        for name, args, job_id in [
            ("import_source", {"source": "https://www.youtube.com/watch?v=fixture"}, "ingest-123"),
            ("transcribe_source", {"source_id": "source-123"}, "transcribe-123"),
            ("preview_edit_plan", {"plan_id": "plan-123"}, "preview-123"),
        ]:
            result = await self.client.call_tool(name, args)
            self.assertFalse(result.is_error, error_text(result))
            self.assertEqual(result.structured_content, {"job_id": job_id, "status": "queued"})
        edition = {"source_id": "source-123", "clips": [{"id": "intro", "start": 0,
                   "end": 1, "title": "Intro"}], "brief": {"goal": "Teach"},
                   "outputs": [{"name": "portrait", "ratio": "9:16"}],
                   "captions": {"mode": "sidecar", "language": "es"},
                   "delivery": "both", "playback_speed": 1.25, "quality": "quality"}
        result = await self.client.call_tool("create_edit_plan", edition)
        self.assertFalse(result.is_error, error_text(result))
        self.assertEqual(result.structured_content["document"], edition)
        self.assertFalse(result.structured_content["approved"])
        transcript = await self.client.call_tool("get_transcript", {
            "source_id": "source-123", "offset": 0, "limit": 1})
        self.assertEqual(transcript.structured_content["segments"][0]["text"], "Hola")
        plan = await self.client.call_tool("get_edit_plan", {"plan_id": "plan-123"})
        self.assertEqual(plan.structured_content["id"], "plan-123")
        job = await self.client.call_tool("get_job", {"job_id": "ingest-123"})
        self.assertEqual(job.structured_content["id"], "ingest-123")


class MCPStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_stdio_initialize_list_and_call(self):
        root = Path(__file__).resolve().parents[1]
        code = ("from test_mcp import FakeService; "
                "from clipear.mcp_server import create_server; "
                "create_server(FakeService()).run(transport='stdio')")
        parameters = StdioServerParameters(command=sys.executable, args=["-c", code],
            cwd=root, env={"PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "tests")))})
        async with Client(parameters, mode="legacy", read_timeout_seconds=10) as client:
            self.assertEqual(client.session.server_info.name, "clipear")
            tools = await client.list_tools()
            self.assertEqual(len(tools.tools), 9)
            result = await client.call_tool("get_job", {"job_id": "persisted-job"})
            self.assertFalse(result.is_error, error_text(result))
            self.assertEqual(result.structured_content["id"], "persisted-job")


class MCPHTTPConfigurationTests(unittest.TestCase):
    def test_http_requires_host_token_even_on_loopback(self):
        from clipear.mcp_server import create_http_app
        with patch.dict(os.environ, {}, clear=True):
            for host in ("127.0.0.1", "0.0.0.0", "::"):
                with self.assertRaisesRegex(ValueError, "CLIPEAR_HTTP_TOKEN"):
                    create_http_app(FakeService(), host=host)


class MCPHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from clipear.mcp_server import create_http_app
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(self.sock.close)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/mcp"
        self.server = uvicorn.Server(uvicorn.Config(
            create_http_app(FakeService(), token="fixture-secret-token"),
            log_level="error", access_log=False))
        self.task = asyncio.create_task(self.server.serve(sockets=[self.sock]))
        for _ in range(500):
            if self.server.started:
                return
            if self.task.done():
                await self.task
            await asyncio.sleep(.01)
        self.fail("HTTP server did not start")

    async def asyncTearDown(self):
        self.server.should_exit = True
        await asyncio.wait_for(self.task, 10)
        self.sock.close()

    async def test_http_rejects_missing_wrong_and_query_tokens_without_cors(self):
        async with httpx2.AsyncClient() as client:
            for headers, suffix in [({}, ""), ({"Authorization": "Bearer wrong"}, ""),
                                    ({}, "?token=fixture-secret-token")]:
                response = await client.post(self.url + suffix, headers=headers, json={})
                self.assertEqual(response.status_code, 401)
                self.assertIn("Bearer", response.headers["www-authenticate"])
                self.assertNotIn("access-control-allow-origin", response.headers)
                self.assertNotIn("fixture-secret-token", response.text)
            denied_origin = await client.post(self.url, headers={
                "Authorization": "Bearer fixture-secret-token", "Origin": "https://evil.example"}, json={})
            self.assertEqual(denied_origin.status_code, 403)

    async def test_actual_authenticated_http_initialize_list_call_and_recover(self):
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer fixture-secret-token"}) as http:
            async with Client(streamable_http_client(self.url, http_client=http),
                              mode="legacy", read_timeout_seconds=10) as client:
                self.assertEqual(client.session.server_info.name, "clipear")
                self.assertEqual(len((await client.list_tools()).tools), 9)
                denied = await client.call_tool("render_approved_plan", {"plan_id": "plan-123"})
                self.assertTrue(denied.is_error)
                ready = await client.call_tool("check_setup")
                self.assertFalse(ready.is_error, error_text(ready))
                self.assertTrue(ready.structured_content["ready"])


if __name__ == "__main__":
    unittest.main()
