import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout
from unittest.mock import patch

from clipear.config import Settings
from clipear.service import Service
from clipear.review import create_review_server, run_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service(Settings(home=Path(self.temp.name)), start_workers=False)
        source_id = "f" * 32
        path = Path(self.temp.name) / "sources" / source_id / "camera.mp4"
        path.parent.mkdir(parents=True); path.write_bytes(b"fixture")
        self.service.store.add_source(source_id, "camera", str(path), hashlib.sha256(b"fixture").hexdigest(), {"duration": 10, "width": 640, "height": 360})
        self.plan = self.service.create_edit_plan(source_id, [{"id": "c1", "title": "<script>danger</script>", "start": 1, "end": 4}], brief={"goal": "Explain"})
        self.server, self.url, self.completed = create_review_server(self.service, self.plan["id"])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, **values):
        data = urllib.parse.urlencode(values).encode()
        origin = urllib.parse.urlsplit(self.url)
        return urllib.request.Request(self.url, data=data, headers={"Origin": f"{origin.scheme}://{origin.netloc}", "Content-Type": "application/x-www-form-urlencoded"})

    def test_html_escapes_untrusted_plan_and_get_never_approves(self):
        with urllib.request.urlopen(self.url) as response:
            html = response.read().decode()
            self.assertIn("&lt;script&gt;danger&lt;/script&gt;", html)
            self.assertNotIn("<script>danger</script>", html)
            self.assertIn("Explain", html)
        self.assertFalse(self.service.get_edit_plan(self.plan["id"])["approved"])

    def test_browser_confirmation_records_only_displayed_digest(self):
        req = self.request(digest=self.plan["digest"], confirm="yes")
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
        self.assertTrue(self.service.get_edit_plan(self.plan["id"])["approved"])
        self.assertTrue(self.completed.is_set())

    def test_external_origin_and_missing_confirmation_fail(self):
        req = self.request(digest=self.plan["digest"], confirm="yes"); req.add_header("Origin", "https://evil.test")
        with self.assertRaises(urllib.error.HTTPError) as blocked:
            urllib.request.urlopen(req)
        self.assertEqual(blocked.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.request(digest=self.plan["digest"]))
        self.assertFalse(self.service.get_edit_plan(self.plan["id"])["approved"])

    def test_plan_changed_during_review_cannot_be_approved(self):
        self.service.create_edit_plan(self.plan["source_id"], [{"id": "c1", "start": 2, "end": 7}], plan_id=self.plan["id"])
        with self.assertRaises(urllib.error.HTTPError) as stale:
            urllib.request.urlopen(self.request(digest=self.plan["digest"], confirm="yes"))
        self.assertEqual(stale.exception.code, 409)
        self.assertFalse(self.service.get_edit_plan(self.plan["id"])["approved"])


    def test_revision_during_preview_cannot_mix_new_plan_with_old_frames(self):
        observed = {}
        requests = []
        frame = Path(self.temp.name) / "captured-preview.png"
        frame.write_bytes(b"old framing fixture")

        def preview(source, directory, document):
            observed["preview_document"] = document
            observed["revised"] = self.service.create_edit_plan(
                self.plan["source_id"],
                [{"id": "c1", "title": "New edition", "start": 6, "end": 9}],
                plan_id=self.plan["id"],
            )
            return [{"path": str(frame), "clip": "c1", "profile": "source"}]

        def inspect_page(url):
            def request_page():
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        observed["html"] = response.read().decode()
                    origin = urllib.parse.urlsplit(url)
                    request = urllib.request.Request(
                        url,
                        data=urllib.parse.urlencode({"digest": observed["revised"]["digest"], "confirm": "yes"}).encode(),
                        headers={"Origin": f"{origin.scheme}://{origin.netloc}", "Content-Type": "application/x-www-form-urlencoded"},
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=5) as response:
                            observed["approval_status"] = response.status
                    except urllib.error.HTTPError as error:
                        observed["approval_status"] = error.code
                except Exception as error:
                    observed["request_error"] = error
            thread = threading.Thread(target=request_page, daemon=True)
            requests.append(thread)
            thread.start()

        with patch.object(self.service, "_media", return_value=SimpleNamespace(preview=preview)), patch("clipear.review.webbrowser.open", side_effect=inspect_page), redirect_stdout(io.StringIO()):
            result = run_review(self.service, self.plan["id"], timeout=1)
        for thread in requests:
            thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
        self.assertNotIn("request_error", observed)
        self.assertEqual(observed["preview_document"], self.plan["document"])
        self.assertIn("1.000–4.000s", observed["html"])
        self.assertNotIn("6.000–9.000s", observed["html"])
        self.assertEqual(observed["approval_status"], 400)
        self.assertFalse(result["approved"])
        self.assertEqual(result["digest"], self.plan["digest"])
        self.assertEqual(result["revision"], self.plan["revision"])
        self.assertFalse(self.service.get_edit_plan(self.plan["id"])["approved"])

    def test_identical_plan_resave_still_requires_review_of_new_revision(self):
        document = self.plan["document"]
        revised = self.service.create_edit_plan(self.plan["source_id"], document["clips"], brief=document["brief"], plan_id=self.plan["id"])
        self.assertEqual(revised["digest"], self.plan["digest"])
        self.assertEqual(revised["revision"], 2)
        with self.assertRaises(urllib.error.HTTPError) as stale:
            urllib.request.urlopen(self.request(digest=self.plan["digest"], confirm="yes"))
        self.assertEqual(stale.exception.code, 409)
        self.assertFalse(self.service.get_edit_plan(self.plan["id"])["approved"])

    def test_browser_shows_boundary_conflicts_and_blocks_confirmation(self):
        plan = self.service.create_edit_plan(self.plan["source_id"], [{"id": "c1", "start": 2, "end": 5}],
                                             captions={"mode": "sidecar", "cues": [{"start": 1, "end": 6, "text": "One complete sentence."}]})
        server, url, completed = create_review_server(self.service, plan["id"])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(url) as response:
                page = response.read().decode()
            self.assertIn("Caption warnings", page)
            self.assertIn("boundary_conflict", page)
            self.assertIn("Approval is blocked", page)
            self.assertIn("source-aligned cues", page)
            self.assertIn('<button type="submit" disabled>', page)
            with patch.object(self, "url", url):
                request = self.request(digest=plan["digest"], confirm="yes")
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(request)
            self.assertEqual(blocked.exception.code, 409)
            self.assertFalse(completed.is_set())
            self.assertFalse(self.service.get_edit_plan(plan["id"])["approved"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
