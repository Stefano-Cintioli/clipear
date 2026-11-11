import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clipear.config import Settings
from clipear.service import Service


def track_worker_observers(test):
    """Retain the real waiter threads without changing detached job behavior."""
    test.worker_observers = []
    def observer_thread(*args, **kwargs):
        observer = threading.Thread(*args, **kwargs)
        test.worker_observers.append(observer)
        return observer
    test.enterContext(patch("clipear.service.threading", SimpleNamespace(Thread=observer_thread)))


def wait_for_worker_observers(test):
    for observer in test.worker_observers:
        # The observer waits/reaps its actual child before finishing its final
        # store transaction. Terminal job status alone cannot prove either.
        observer.join(timeout=45)
        test.assertFalse(observer.is_alive(), "Worker observer did not finish before workspace cleanup")


class WorkerExitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(home=Path(self.temp.name) / "data")
        self.service = Service(self.settings)
        track_worker_observers(self)

    def tearDown(self):
        wait_for_worker_observers(self)
        self.temp.cleanup()

    def launch_exiting_worker(self, job_id, returncode):
        actual_popen = subprocess.Popen
        child = []
        def exit_before_work(command, **kwargs):
            process = actual_popen([sys.executable, "-c", f"import sys; print('early worker exit evidence', flush=True); sys.exit({returncode})"], **kwargs)
            child.append(process)
            return process
        with patch("clipear.service.subprocess.Popen", side_effect=exit_before_work):
            self.service._launch(job_id)
        child[0].wait(timeout=5)
        return child[0]

    def test_observed_worker_exit_fails_remaining_queued_or_running_job(self):
        for running, returncode in ((False, 23), (True, 23), (False, 0)):
            with self.subTest(running=running, returncode=returncode):
                job_id = self.service.store.new_job("preview", {})
                if running:
                    self.service.store.claim_job(job_id)
                self.launch_exiting_worker(job_id, returncode)
                wait_for_worker_observers(self)
                job = self.service.get_job(job_id)
                self.assertEqual(job["status"], "failed", job)
                self.assertIn(f"return code {returncode}", job["error"])
                log = self.settings.home / "jobs" / job_id / "worker.log"
                self.assertIn(str(log), job["error"])
                self.assertIn("early worker exit evidence", log.read_text())
                with self.service.store.connect() as db:
                    events = db.execute("SELECT detail FROM events WHERE entity=? AND action='job_failed'", (job_id,)).fetchall()
                self.assertEqual(len(events), 1)
                self.assertEqual(json.loads(events[0]["detail"])["returncode"], returncode)

    def test_observed_worker_exit_preserves_already_terminal_state(self):
        for error in (None, "Explicit failure with useful evidence"):
            with self.subTest(error=error):
                job_id = self.service.store.new_job("preview", {})
                self.service.store.finish_job(job_id, result={"previews": []}, error=error)
                before = self.service.get_job(job_id)
                self.launch_exiting_worker(job_id, 23)
                wait_for_worker_observers(self)
                self.assertEqual(self.service.get_job(job_id), before)

    def test_teardown_waits_for_observer_after_job_is_terminal(self):
        job_id = self.service.store.new_job("preview", {})
        self.service.store.finish_job(job_id, result={"previews": []})
        entered, release = threading.Event(), threading.Event()
        original_observation = self.service.store.worker_exited
        def delayed_observation(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Fixture never released the worker observer")
            original_observation(*args)
        with patch.object(self.service.store, "worker_exited", side_effect=delayed_observation):
            self.launch_exiting_worker(job_id, 0)
            self.assertTrue(entered.wait(5), "Worker exited without reaching its observer")
            observer = self.worker_observers[0]
            self.assertEqual(self.service.get_job(job_id)["status"], "succeeded")
            original_join, original_cleanup = observer.join, self.temp.cleanup
            def release_then_join(*args, **kwargs):
                release.set()
                original_join(*args, **kwargs)
            def cleanup_after_observation():
                self.assertFalse(observer.is_alive(), "Job status is terminal, but its observer still owns the workspace")
                original_cleanup()
            try:
                with patch.object(observer, "join", side_effect=release_then_join), patch.object(self.temp, "cleanup", side_effect=cleanup_after_observation):
                    self.tearDown()
                self.assertFalse(self.settings.home.exists())
            finally:
                release.set()
                original_join(timeout=5)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / "camera files"; self.inputs.mkdir()
        self.source = self.inputs / "my video.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", "sine=frequency=600:sample_rate=48000", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.source)], check=True, capture_output=True)
        self.before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.settings = Settings(home=self.root / "data", input_roots=(self.inputs,))
        self.service = Service(self.settings)
        track_worker_observers(self)

    def tearDown(self):
        wait_for_worker_observers(self)
        self.temp.cleanup()

    def wait(self, job_id):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            job = self.service.get_job(job_id)
            if job["status"] in {"failed", "succeeded"}:
                self.assertEqual(job["status"], "succeeded", job)
                wait_for_worker_observers(self)
                return job["result"]
            time.sleep(.05)
        self.fail(f"Worker did not finish: {self.service.get_job(job_id)}")

    def test_detached_import_finishes_after_invoking_cli_exits(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run([sys.executable, "-m", "clipear", "--home", str(self.settings.home), "--input-root", str(self.inputs), "import", str(self.source)], env=env, text=True, capture_output=True, check=True)
        job = json.loads(result.stdout)
        imported = self.wait(job["job_id"])
        self.assertEqual(imported["sha256"], self.before)
        self.assertNotEqual(Path(imported["path"]), self.source)
        self.assertEqual(self.service.store.get_source(imported["source_id"])["info"]["width"], 320)

    def test_worker_launch_does_not_leak_a_running_popen_handle(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            self.wait(self.service.import_source(str(self.source))["job_id"])
        self.assertFalse([w for w in caught if issubclass(w.category, ResourceWarning)], [str(w.message) for w in caught])

    def test_actual_approved_snapshot_exports_clean_and_finished_files(self):
        imported = self.wait(self.service.import_source(str(self.source))["job_id"])
        plan = self.service.create_edit_plan(imported["source_id"], [{"id": "idea", "start": .4, "end": 2.4}], outputs=[{"name": "portrait", "ratio": "9:16", "height": 320}], captions={"mode": "burn", "cues": [{"start": .5, "end": 2.2, "text": "One complete idea"}]}, delivery="both", playback_speed=2)
        with self.assertRaises(PermissionError):
            self.service.render_approved_plan(plan["id"])
        # Test fixture simulates the separate trusted human confirmation path.
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        result = self.wait(self.service.render_approved_plan(plan["id"])["job_id"])
        self.assertEqual(result["digest"], plan["digest"])
        mp4s = [item for item in result["outputs"] if Path(item["path"]).suffix == ".mp4"]
        self.assertEqual({item["kind"] for item in mp4s}, {"clean", "finished"})
        for item in mp4s:
            self.assertTrue(Path(item["path"]).is_file())
            self.assertEqual(item["probe"]["width"], 180)
            self.assertEqual(item["probe"]["height"], 320)
            self.assertAlmostEqual(item["probe"]["duration"], 1, delta=.15)
            self.assertTrue(item["probe"]["has_audio"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.before)

    def test_simultaneous_workers_claim_once_with_audit_evidence(self):
        job = self.service.store.new_job("preview", {})
        barrier = threading.Barrier(8)
        results = []
        def attempt():
            barrier.wait(); results.append(self.service.store.claim_job(job))
        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(results.count(True), 1)
        with self.service.store.connect() as db:
            events = db.execute("SELECT * FROM events WHERE action='job_claimed' AND entity=?", (job,)).fetchall()
        self.assertEqual(len(events), 1)
        self.service.store.finish_job(job, error="Fixture complete")


if __name__ == "__main__":
    unittest.main()
