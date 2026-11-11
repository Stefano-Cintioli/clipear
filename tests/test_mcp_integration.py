"""Production CLI/Service/worker integration over actual SDK stdio connections."""

import asyncio
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters

from clipear.config import Settings
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
        package_root = Path(__file__).resolve().parents[1]
        self.parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "clipear", "--home", str(self.home),
                  "--input-root", str(self.inputs), "mcp"],
            cwd=package_root,
            env={"PYTHONPATH": str(package_root / "src"),
                 "CLIPEAR_FFMPEG": self.ffmpeg, "CLIPEAR_FFPROBE": self.ffprobe},
        )

    def connect(self):
        return Client(self.parameters, mode="legacy", read_timeout_seconds=15)

    def successful_result(self, result):
        detail = " ".join(item.text for item in result.content if hasattr(item, "text"))
        self.assertFalse(result.is_error, detail)
        return result.structured_content

    async def wait_for_job(self, job_id):
        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            job = self.service.get_job(job_id)
            if job["status"] in {"succeeded", "failed"}:
                self.assertEqual(job["status"], "succeeded", job)
                return job
            await asyncio.sleep(.05)
        self.fail(f"Detached worker did not finish: {self.service.get_job(job_id)}")

    async def test_disconnect_import_reconnect_plan_and_approved_render(self):
        async with self.connect() as client:
            self.assertEqual(client.session.server_info.name, "clipear")
            tools = (await client.list_tools()).tools
            self.assertFalse(any("approv" in tool.name and tool.name != "render_approved_plan"
                                 for tool in tools))
            imported_job = self.successful_result(await client.call_tool(
                "import_source", {"source": str(self.source)}))
            self.assertIn(imported_job["status"], {"queued", "running", "succeeded"})

        # This poll happens only after the real MCP subprocess has disconnected.
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
