"""Production workers over real SDK transports, including Windows stdio limits."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
import uvicorn

from clipear.config import Settings
from clipear.mcp_server import create_http_app
from clipear.service import Service


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class MCPProductionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="clipear mcp integration ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.inputs = self.root / "camera files"
        self.inputs.mkdir()
        self.source = self.inputs / "camera's original.mp4"
        self.home = self.root / "private jobs"
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=20:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(self.source),
        ], check=True, capture_output=True, timeout=30)
        self.source_sha256 = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.service = Service(Settings(home=self.home, ffmpeg=self.ffmpeg,
            ffprobe=self.ffprobe, input_roots=(self.inputs,)), start_workers=False)
        self.http_url = None
        self.http_server = None
        self.http_task = None
        self.worker_observers = []
        self.observer_patcher = None
        package_root = Path(__file__).resolve().parents[1]
        self.parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "clipear", "--home", str(self.home),
                  "--input-root", str(self.inputs), "mcp"],
            cwd=package_root,
            env={"PYTHONPATH": str(package_root / "src"),
                 "CLIPEAR_FFMPEG": self.ffmpeg, "CLIPEAR_FFPROBE": self.ffprobe},
        )

    @asynccontextmanager
    async def connect(self):
        if self.http_url is None:
            async with Client(self.parameters, mode="legacy", read_timeout_seconds=15) as client:
                yield client
        else:
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer fixture-http-secret"}) as http:
                async with Client(streamable_http_client(self.http_url, http_client=http),
                                  mode="legacy", read_timeout_seconds=15) as client:
                    yield client

    async def start_http_server(self):
        # This production Service host lives outside the SDK stdio subprocess's
        # Windows Job Object, as a separately launched HTTP host does in use.
        # Capture its real observer threads so their process handles/log files
        # are closed before TemporaryDirectory cleanup, including on Windows.
        original_thread = threading.Thread

        def capture_observer(*args, **kwargs):
            thread = original_thread(*args, **kwargs)
            self.worker_observers.append(thread)
            return thread

        self.observer_patcher = patch("clipear.service.threading", SimpleNamespace(Thread=capture_observer))
        self.observer_patcher.start()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        self.http_url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
        http_service = Service(self.service.settings)
        self.http_server = uvicorn.Server(uvicorn.Config(
            create_http_app(http_service, token="fixture-http-secret"),
            log_level="error", access_log=False))
        self.http_task = asyncio.create_task(self.http_server.serve(sockets=[sock]))
        for _ in range(500):
            if self.http_server.started:
                return
            if self.http_task.done():
                await self.http_task
            await asyncio.sleep(.01)
        self.fail("Production HTTP host did not start")

    async def asyncTearDown(self):
        try:
            if self.http_task is not None:
                self.http_server.should_exit = True
                await asyncio.wait_for(self.http_task, 10)
            for thread in self.worker_observers:
                await asyncio.to_thread(thread.join, 10)
                self.assertFalse(thread.is_alive(), "Worker observer still owns its process/log handles")
        finally:
            if self.observer_patcher is not None:
                self.observer_patcher.stop()

    def successful_result(self, result):
        detail = " ".join(item.text for item in result.content if hasattr(item, "text"))
        self.assertFalse(result.is_error, detail)
        return result.structured_content

    async def wait_for_job(self, job_id):
        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            job = self.service.get_job(job_id)
            if job["status"] in {"succeeded", "failed"}:
                self.assertEqual(job["status"], "succeeded", self.job_diagnostics(job_id))
                return job
            await asyncio.sleep(.05)
        self.fail("Detached worker did not finish: " + self.job_diagnostics(job_id))

    def job_diagnostics(self, job_id):
        directory = self.home / "jobs" / job_id
        logs = {str(path.relative_to(directory)): path.read_bytes()[-16000:].decode("utf-8", "replace")
                for path in directory.rglob("*.log")}
        with self.service.store.connect() as db:
            events = [dict(row) for row in db.execute(
                "SELECT at,action,entity,detail FROM events WHERE entity=? ORDER BY seq", (job_id,))]
        # Include evidence in the CI failure itself before TemporaryDirectory
        # cleanup removes the SQLite store and worker/subprocess logs.
        return json.dumps({"job": self.service.get_job(job_id), "logs": logs,
                           "events": events}, sort_keys=True)

    async def test_disconnect_import_reconnect_plan_and_approved_render(self):
        if sys.platform == "win32":
            # Native Windows stdio explicitly rejects background submission:
            # the SDK kills all server Job Object descendants at disconnect.
            async with self.connect() as client:
                setup = self.successful_result(await client.call_tool("check_setup"))
                self.assertFalse(setup["mcp_transport"]["background_jobs_supported"])
                self.assertIn("separately", setup["mcp_transport"]["limitation"])
                for name, arguments in [
                    ("import_source", {"source": str(self.source)}),
                    ("transcribe_source", {"source_id": "a" * 32}),
                    ("preview_edit_plan", {"plan_id": "b" * 32}),
                    ("render_approved_plan", {"plan_id": "b" * 32}),
                ]:
                    denied = await client.call_tool(name, arguments)
                    self.assertTrue(denied.is_error)
                    self.assertTrue(any("streamable-http" in getattr(item, "text", "")
                                        for item in denied.content))
            with self.service.store.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        else:
            await self.exercise_disconnect_workflow()

        # Every native platform runs actual HTTP disconnect coverage. Windows
        # uses this transport for the supported durable background workflow.
        await self.start_http_server()
        await self.exercise_disconnect_workflow()

    async def exercise_disconnect_workflow(self):
        async with self.connect() as client:
            self.assertEqual(client.session.server_info.name, "clipear")
            setup = self.successful_result(await client.call_tool("check_setup"))
            self.assertTrue(setup["mcp_transport"]["background_jobs_supported"])
            self.assertEqual(setup["mcp_transport"]["name"],
                             "streamable-http" if self.http_url else "stdio")
            tools = (await client.list_tools()).tools
            self.assertFalse(any("approv" in tool.name and tool.name != "render_approved_plan"
                                 for tool in tools))
            imported_job = self.successful_result(await client.call_tool(
                "import_source", {"source": str(self.source)}))
            self.assertIn(imported_job["status"], {"queued", "running", "succeeded"})

        # Poll only after the real SDK client closes its transport connection.
        imported = (await self.wait_for_job(imported_job["job_id"]))["result"]
        self.assertEqual(imported["sha256"], self.source_sha256)
        self.assertNotEqual(Path(imported["path"]), self.source)
        self.assertTrue(Path(imported["path"]).is_relative_to(self.home))

        async with self.connect() as client:
            persisted = self.successful_result(await client.call_tool(
                "get_job", {"job_id": imported_job["job_id"]}))
            self.assertEqual(persisted["status"], "succeeded")
            self.assertEqual(persisted["result"]["source_id"], imported["source_id"])
            plan = self.successful_result(await client.call_tool("create_edit_plan", {
                "source_id": imported["source_id"],
                "clips": [{"id": "opening", "title": "Opening", "start": .25, "end": 1.25}],
                "outputs": [{"name": "original", "ratio": "source", "height": 90}],
                "captions": {"mode": "none"}, "delivery": "clean", "quality": "fast",
            }))
            self.assertFalse(plan["approved"])
            denied = await client.call_tool("render_approved_plan", {"plan_id": plan["id"]})
            self.assertTrue(denied.is_error)
            self.assertTrue(any("Human approval" in getattr(item, "text", "")
                                for item in denied.content))
            absent = await client.call_tool("approve_plan", {"plan_id": plan["id"]})
            self.assertTrue(absent.is_error)

        # Only the TEST fixture simulates the separate trusted human review path.
        # The SDK connection is closed; no MCP tool or input can perform this call.
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])

        async with self.connect() as client:
            approved = self.successful_result(await client.call_tool(
                "get_edit_plan", {"plan_id": plan["id"]}))
            self.assertTrue(approved["approved"])
            render_job = self.successful_result(await client.call_tool(
                "render_approved_plan", {"plan_id": plan["id"]}))

        rendered = (await self.wait_for_job(render_job["job_id"]))["result"]
        self.assertEqual(rendered["digest"], plan["digest"])
        self.assertEqual(rendered["revision"], plan["revision"])
        self.assertTrue(rendered["verification"]["ok"])
        videos = [output for output in rendered["outputs"] if output["kind"] == "clean"]
        self.assertEqual(len(videos), 1)
        video = videos[0]
        self.assertTrue(Path(video["path"]).is_file())
        self.assertEqual(hashlib.sha256(Path(video["path"]).read_bytes()).hexdigest(), video["sha256"])
        probe = video["probe"]
        self.assertEqual((probe["width"], probe["height"]), (160, 90))
        self.assertAlmostEqual(probe["duration"], 1, delta=.1)
        self.assertEqual(probe["video_codec"], "h264")
        self.assertEqual(probe["pixel_format"], "yuv420p")
        self.assertEqual(probe["audio_codec"], "aac")
        self.assertTrue(probe["has_audio"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_sha256)

        async with self.connect() as client:
            persisted_render = self.successful_result(await client.call_tool(
                "get_job", {"job_id": render_job["job_id"]}))
            self.assertEqual(persisted_render["status"], "succeeded")
            self.assertEqual(persisted_render["result"]["outputs"][0]["sha256"], video["sha256"])


if __name__ == "__main__":
    unittest.main()
