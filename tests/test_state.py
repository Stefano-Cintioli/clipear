import hashlib
import io
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from clipear.cli import approve_interactively
from clipear.config import Settings
from clipear.service import Service


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / "camera files"
        self.inputs.mkdir()
        self.settings = Settings(home=self.root / "data", input_roots=(self.inputs,))
        self.service = Service(self.settings, start_workers=False)
        self.source_id = "a" * 32
        self.source = self.settings.home / "sources" / self.source_id / "source.mp4"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"source fixture")
        self.service.store.add_source(
            self.source_id, "camera.mp4", str(self.source),
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
            {"duration": 20.0, "width": 1280, "height": 720, "has_audio": True},
        )

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **kwargs):
        return self.service.create_edit_plan(
            self.source_id, [{"id": "c1", "title": "An idea", "start": 1, "end": 6}], **kwargs
        )

    def test_render_requires_human_approval_and_exact_revision(self):
        plan = self.plan()
        with self.assertRaises(PermissionError):
            self.service.render_approved_plan(plan["id"])
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        job = self.service.render_approved_plan(plan["id"])
        self.assertEqual(self.service.get_job(job["job_id"])["status"], "queued")
        changed = self.plan(brief={"goal": "A different objective"}, plan_id=plan["id"])
        self.assertEqual(changed["revision"], 2)
        self.assertFalse(changed["approved"])
        with self.assertRaises(PermissionError):
            self.service.render_approved_plan(changed["id"])
        with self.assertRaises(PermissionError):
            self.service.store.approve(changed["id"], plan["digest"], plan["revision"])

    def test_queued_render_freezes_approved_snapshot(self):
        plan = self.plan()
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        job = self.service.render_approved_plan(plan["id"])
        self.plan(playback_speed=2, plan_id=plan["id"])
        request = self.service.store.job_request(job["job_id"])
        self.assertEqual(request["plan"]["playback_speed"], 1)
        self.assertEqual(request["digest"], plan["digest"])

    def test_modified_source_cannot_use_previous_approval(self):
        plan = self.plan()
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        self.source.write_bytes(b"different source")
        with self.assertRaises(PermissionError):
            self.service.render_approved_plan(plan["id"])

    def test_invalid_ranges_and_unsafe_names_are_rejected(self):
        for start, end in [(-1, 2), (2, 1), (1, 21), (math.nan, 3), (1, math.inf)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.service.create_edit_plan(self.source_id, [{"id": "c1", "start": start, "end": end}])
        with self.assertRaises(ValueError):
            self.service.create_edit_plan(self.source_id, [{"id": "../escape", "start": 1, "end": 3}])
        with self.assertRaises(ValueError):
            self.plan(outputs=[{"name": "../escape", "ratio": "9:16"}])

    def test_inputs_are_host_scoped_and_youtube_urls_checked(self):
        outside = self.root / "private.mp4"
        outside.write_bytes(b"private")
        with self.assertRaises(PermissionError):
            self.service.import_source(str(outside))
        allowed = self.inputs / "my camera.mp4"
        allowed.write_bytes(b"camera")
        self.assertEqual(self.service.import_source(str(allowed))["status"], "queued")
        for url in ["http://127.0.0.1/private", "https://youtube.com.evil.test/watch?v=1", "https://user:pass@youtube.com/watch?v=1", "-exec=oops"]:
            with self.subTest(url=url), self.assertRaises((ValueError, FileNotFoundError)):
                self.service.import_source(url)

    def test_transcript_paging_and_explicit_empty_captions(self):
        segments = [{"start": i, "end": i+.5, "text": f"line {i}"} for i in range(10)]
        self.service.store.set_transcript(self.source_id, {"language": "en", "segments": segments})
        page = self.service.get_transcript(self.source_id, offset=2, limit=3)
        self.assertEqual(page["segments"], segments[2:5])
        self.assertEqual(page["next_offset"], 5)
        self.assertEqual(page["total"], 10)
        with self.assertRaises(ValueError):
            self.service.get_transcript(self.source_id, limit=201)
        default = self.plan(captions={"mode": "sidecar"})
        self.assertEqual(len(default["document"]["captions"]["cues"]), 10)
        explicit = self.plan(captions={"mode": "sidecar", "cues": []})
        self.assertEqual(explicit["document"]["captions"]["cues"], [])

    def test_job_claim_happens_once_and_failure_is_persisted(self):
        job_id = self.service.store.new_job("preview", {"plan": {}})
        self.assertTrue(self.service.store.claim_job(job_id))
        self.assertFalse(self.service.store.claim_job(job_id))
        self.service.store.finish_job(job_id, error="Specific failure")
        job = self.service.get_job(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "Specific failure")

    def test_all_output_and_caption_changes_invalidate_approval(self):
        original = self.plan(captions={"mode": "sidecar", "cues": [{"start": 1, "end": 3, "text": "Hello"}]})
        for changed in [
            {"outputs": [{"name": "vertical", "ratio": "9:16", "height": 1920, "fit": "crop"}]},
            {"captions": {"mode": "sidecar", "cues": [{"start": 1, "end": 3, "text": "Translated"}]}},
            {"quality": "fast"}, {"playback_speed": .5},
        ]:
            current = self.service.get_edit_plan(original["id"])
            self.service.store.approve(current["id"], current["digest"], current["revision"])
            revised = self.plan(plan_id=current["id"], **changed)
            self.assertFalse(revised["approved"])

    def test_caption_boundary_warnings_are_visible_and_block_approval_until_corrected(self):
        self.service.store.set_transcript(self.source_id, {"language": "en", "segments": [{"start": 0, "end": 10.4, "text": "Words across the cut boundary"}]})
        plan = self.plan(captions={"mode": "sidecar"})
        for result in (plan, self.service.get_edit_plan(plan["id"])):
            conflicts = [warning for warning in result.get("warnings", []) if warning["code"] == "boundary_conflict"]
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0]["clip"], "c1")
        with self.assertRaisesRegex((PermissionError, ValueError), "boundary"):
            self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        self.assertFalse(self.service.get_edit_plan(plan["id"])["approved"])
        corrected = self.plan(plan_id=plan["id"], captions={"mode": "sidecar", "cues": [{"start": 1, "end": 6, "text": "Correct source-aligned words"}]})
        self.assertNotIn("boundary_conflict", [warning["code"] for warning in corrected["warnings"]])
        self.service.store.approve(corrected["id"], corrected["digest"], corrected["revision"])
        self.assertEqual(self.service.render_approved_plan(corrected["id"])["status"], "queued")

    def test_caption_boundary_guard_also_blocks_legacy_approved_render(self):
        plan = self.plan(captions={"mode": "burn", "cues": [{"start": 0, "end": 8, "text": "Unresolved boundary words"}]}, delivery="finished")
        # Fixture represents approval recorded by a version without this guard.
        with self.service.store.connect() as db:
            db.execute("UPDATE plans SET approved_digest=digest,approved_at=1 WHERE id=?", (plan["id"],))
        with self.assertRaisesRegex((PermissionError, ValueError), "boundary"):
            self.service.render_approved_plan(plan["id"])

    def test_terminal_review_displays_caption_conflicts_before_prompting(self):
        plan = self.plan(captions={"mode": "sidecar", "cues": [{"start": 0, "end": 8, "text": "Words outside the cut"}]})
        out = io.StringIO()
        with redirect_stdout(out), patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch("builtins.input", side_effect=AssertionError("Conflicted captions must not reach the approval prompt")):
            with self.assertRaisesRegex((PermissionError, ValueError), "boundary"):
                approve_interactively(self.service, plan["id"])
        self.assertIn("boundary_conflict", out.getvalue())

    def test_captions_none_ignores_boundary_conflicts(self):
        plan = self.plan(captions={"mode": "none", "cues": [{"start": 0, "end": 8, "text": "Unused"}]})
        self.assertEqual(plan.get("warnings", []), [])
        self.service.store.approve(plan["id"], plan["digest"], plan["revision"])
        self.assertEqual(self.service.render_approved_plan(plan["id"])["status"], "queued")


if __name__ == "__main__":
    unittest.main()
