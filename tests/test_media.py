"""Real FFmpeg fixtures stay temporary; no source media is tracked."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from clipear.media import Media, MediaError
except ImportError:
    Media = MediaError = None


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe required")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="clipear test '")
        cls.root = Path(cls.temporary.name)
        cls.landscape = cls.root / "camera [landscape] ' source.mp4"
        cls.portrait = cls.root / "portrait silent.mp4"
        cls.make_fixture(cls.landscape, "160x90", True)
        cls.make_fixture(cls.portrait, "90x160", False)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def make_fixture(cls, path, size, audio):
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration=4"]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "120", "-preset", "ultrafast"]
        if audio:
            command += ["-c:a", "aac"]
        command += [str(path)]
        subprocess.run(command, check=True, capture_output=True)

    def setUp(self):
        self.assertIsNotNone(Media, "portable Media engine is not implemented")
        self.work = Path(tempfile.mkdtemp(dir=self.root, prefix="job "))
        self.settings = SimpleNamespace(home=self.root, ffmpeg="ffmpeg", ffprobe="ffprobe", yt_dlp="yt-dlp", whisper_cli=None, whisper_model=None, input_roots=(self.root,))
        self.media = Media(self.settings)

    def plan(self, **changes):
        plan = {"version": 1, "source_id": "source", "source_sha256": hashlib.sha256(self.landscape.read_bytes()).hexdigest(), "brief": {},
                "clips": [{"id": "clip-one", "title": "Opening", "start": 0.35, "end": 1.65}],
                "outputs": [{"name": "original", "ratio": "source", "height": 90, "fit": "pad", "position": "center"}],
                "captions": {"mode": "none", "language": "en"}, "delivery": "clean", "playback_speed": 1.0, "quality": "fast"}
        plan.update(changes)
        return plan

    def test_local_import_copies_fingerprints_and_never_changes_camera_file(self):
        before = self.landscape.read_bytes()
        imported = self.media.ingest(str(self.landscape), self.work)
        self.assertNotEqual(Path(imported["path"]), self.landscape)
        self.assertEqual(Path(imported["path"]).read_bytes(), before)
        self.assertEqual(imported["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual((imported["info"]["width"], imported["info"]["height"]), (160, 90))
        self.assertTrue(imported["info"]["has_audio"])
        self.assertEqual(self.landscape.read_bytes(), before)

    def test_import_refuses_outside_roots_symlinks_and_option_like_urls(self):
        self.settings.input_roots = (self.work,)
        sources = [str(self.landscape), "--exec=touch bad", "https://youtube.com.evil.test/watch?v=abc", "https://example.com/video", "https://youtube.com/watch?v=abc\n--exec=x"]
        for source in sources:
            with self.subTest(source=source), self.assertRaises((ValueError, MediaError)):
                self.media.ingest(source, self.work)
        with self.subTest(source="symlink escape"):
            link = self.work / "escape.mp4"
            try:
                link.symlink_to(self.landscape)
            except OSError:
                # Developer Mode may be unavailable on Windows; the independent
                # root and URL checks above still run on every platform.
                self.skipTest("OS permission does not allow creating a test symlink")
            with self.assertRaises((ValueError, MediaError)):
                self.media.ingest(str(link), self.work)

    def test_exact_clean_trim_has_expected_duration_codec_and_first_frame(self):
        before = hashlib.sha256(self.landscape.read_bytes()).hexdigest()
        events = []
        plan = self.plan()
        frozen = copy.deepcopy(plan)
        result = self.media.render(self.landscape, self.work, plan, [], lambda fraction, message: events.append((fraction, message)))
        video = result["outputs"][0]
        probe = video["probe"]
        self.assertEqual(video["kind"], "clean")
        self.assertEqual((probe["width"], probe["height"]), (160, 90))
        self.assertAlmostEqual(probe["duration"], 1.3, delta=0.08)
        self.assertTrue(probe["has_audio"])
        self.assertEqual(probe["video_codec"], "h264")
        self.assertEqual(probe["pixel_format"], "yuv420p")
        self.assertEqual(probe["audio_codec"], "aac")
        self.assertEqual(probe["sample_aspect_ratio"], "1:1")
        self.assertTrue(result["verification"]["ok"])
        self.assertEqual(before, hashlib.sha256(self.landscape.read_bytes()).hexdigest())
        self.assertEqual(plan, frozen)
        self.assertEqual(events[-1][0], 1.0)
        self.assertTrue(all(0 <= fraction <= 1 for fraction, _ in events))
        source_frame = self.raw_frame(self.landscape, 0.35)
        output_frame = self.raw_frame(Path(video["path"]), 0)
        self.assertLess(sum(abs(a - b) for a, b in zip(source_frame, output_frame)) / len(source_frame), 15)

    @staticmethod
    def raw_frame(path, at=0):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout

    def test_every_ratio_pad_and_crop_from_landscape_and_silent_portrait(self):
        dimensions = {"source": {self.landscape: (284, 160), self.portrait: (90, 160)}, "16:9": (284, 160), "9:16": (90, 160), "1:1": (160, 160), "4:5": (128, 160)}
        for source in (self.landscape, self.portrait):
            for ratio, expected in dimensions.items():
                for fit in ("pad", "crop"):
                    with self.subTest(source=source.name, ratio=ratio, fit=fit):
                        profile = {"name": "profile", "ratio": ratio, "height": 160, "fit": fit, "position": "right"}
                        destination = self.work / f"{source.stem[:4]}-{ratio.replace(':', '-')}-{fit}"
                        plan = self.plan(outputs=[profile], source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                        result = self.media.render(source, destination, plan, [])
                        probe = result["outputs"][0]["probe"]
                        self.assertEqual((probe["width"], probe["height"]), expected[source] if isinstance(expected, dict) else expected)
                        self.assertEqual(probe["has_audio"], source == self.landscape)

    def test_speed_retimes_audio_and_agent_cues_in_source_seconds(self):
        cues = [{"start": 0.5, "end": 1.0, "text": "Olá"}, {"start": 1.0, "end": 2.5, "text": "BNB"}]
        plan = self.plan(clips=[{"id": "clip-one", "title": "Speed", "start": 0.5, "end": 2.5}], captions={"mode": "sidecar", "language": "pt", "cues": cues}, playback_speed=2)
        frozen = copy.deepcopy(plan)
        result = self.media.render(self.landscape, self.work, plan, [{"start": 0, "end": 3, "text": "Wrong transcript"}])
        video = next(item for item in result["outputs"] if item["kind"] == "clean")
        srt = next(item for item in result["outputs"] if item["kind"] == "sidecar")
        self.assertAlmostEqual(video["probe"]["duration"], 1.0, delta=0.08)
        audio = next(stream for stream in video["probe"]["streams"] if stream["codec_type"] == "audio")
        self.assertAlmostEqual(float(audio["duration"]), 1, delta=0.08)
        self.assertEqual(Path(srt["path"]).read_text(), "1\n00:00:00,000 --> 00:00:00,250\nOlá\n\n2\n00:00:00,250 --> 00:00:01,000\nBNB\n\n")
        self.assertEqual(plan, frozen)

    def test_partial_caption_cues_fail_before_writing_any_output(self):
        for mode in ("sidecar", "burn"):
            with self.subTest(mode=mode):
                destination = self.work / mode
                # The second clip conflicts: preflight must also prevent the first
                # clip from leaving an apparently usable subtitle/video artifact.
                plan = self.plan(clips=[{"id": "whole", "start": 0, "end": 3}, {"id": "partial", "start": 1, "end": 2}],
                                 captions={"mode": mode, "cues": [{"start": 0, "end": 3, "text": "Words across both clip boundaries"}]}, delivery="finished")
                with self.assertRaisesRegex((MediaError, PermissionError, ValueError), "boundary"):
                    self.media.render(self.landscape, destination, plan, [])
                self.assertFalse(destination.exists() and any(destination.iterdir()))

    def test_clean_and_finished_are_separate_and_burn_changes_pixels(self):
        plan = self.plan(delivery="both", captions={"mode": "burn", "language": "en", "cues": [{"start": 0.35, "end": 1.65, "text": "Visible caption"}]}, outputs=[{"name": "square", "ratio": "1:1", "height": 160, "fit": "pad", "position": "center"}])
        result = self.media.render(self.landscape, self.work, plan, [])
        clean = next(item for item in result["outputs"] if item["kind"] == "clean")
        finished = next(item for item in result["outputs"] if item["kind"] == "finished")
        self.assertNotEqual(Path(clean["path"]), Path(finished["path"]))
        self.assertNotEqual(self.raw_frame(Path(clean["path"]), 0.5), self.raw_frame(Path(finished["path"]), 0.5))
        self.assertTrue(any(item["kind"] == "sidecar" for item in result["outputs"]))

    def test_preview_creates_one_framed_still_per_clip_and_profile(self):
        plan = self.plan(outputs=[{"name": "portrait", "ratio": "9:16", "height": 160, "fit": "crop", "position": "left"}])
        previews = self.media.preview(self.landscape, self.work, plan)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0]["clip"], "clip-one")
        self.assertEqual(previews[0]["profile"], "portrait")
        probe = self.media.inspect(Path(previews[0]["path"]))
        self.assertEqual((probe["width"], probe["height"]), (90, 160))

    def test_missing_whisper_and_silent_source_have_explicit_errors(self):
        with self.assertRaisesRegex(MediaError, "whisper|Whisper"):
            self.media.transcribe(self.landscape, self.work)
        self.settings.whisper_cli = "not-installed-whisper-cli"
        self.settings.whisper_model = self.work / "model.bin"
        with self.assertRaisesRegex(MediaError, "audio"):
            self.media.transcribe(self.portrait, self.work)

    def test_failed_subprocess_retains_log_and_error_is_actionable(self):
        self.settings.ffmpeg = "not-installed-clipear-ffmpeg"
        with self.assertRaisesRegex(MediaError, "log|Log"):
            self.media.render(self.landscape, self.work, self.plan(), [])
        self.assertTrue(list(self.work.glob("*.log")))

    def test_invalid_camera_import_retains_probe_failure_log(self):
        camera = self.work / "broken.mp4"
        camera.write_bytes(b"invalid camera container")
        destination = self.work / "failed-import"
        with self.assertRaises(MediaError):
            self.media.ingest(str(camera), destination)
        logs = list(destination.glob("*.log"))
        self.assertTrue(logs, "failed import must retain the probe error")
        self.assertIn("ffprobe", logs[0].read_text())

    def test_render_rejects_path_escape_profiles_and_changed_source_digest(self):
        for plan in [self.plan(outputs=[{"name": "../escape", "ratio": "source", "height": 90, "fit": "pad", "position": "center"}]), self.plan(source_sha256="0" * 64)]:
            with self.subTest(plan=plan), self.assertRaises((ValueError, MediaError)):
                self.media.render(self.landscape, self.work, plan, [])

    def test_slow_playback_preserves_audio_and_explicit_empty_cues(self):
        plan = self.plan(playback_speed=0.5, captions={"mode": "sidecar", "cues": []})
        result = self.media.render(self.landscape, self.work, plan, [{"start": 0.35, "end": 1.65, "text": "Must not leak into empty approved cues"}])
        video = next(item for item in result["outputs"] if item["kind"] == "clean")
        srt = next(item for item in result["outputs"] if item["kind"] == "sidecar")
        self.assertAlmostEqual(video["probe"]["duration"], 2.6, delta=0.08)
        audio = next(stream for stream in video["probe"]["streams"] if stream["codec_type"] == "audio")
        self.assertAlmostEqual(float(audio["duration"]), 2.6, delta=0.08)
        self.assertEqual(Path(srt["path"]).read_text(), "")

    def test_pad_has_bars_and_crop_uses_distinct_left_and_right_framing(self):
        frames = {}
        for fit, position in (("pad", "center"), ("crop", "left"), ("crop", "right")):
            profile = {"name": "square", "ratio": "1:1", "height": 160, "fit": fit, "position": position}
            result = self.media.render(self.landscape, self.work / f"{fit}-{position}", self.plan(outputs=[profile]), [])
            frames[(fit, position)] = self.raw_frame(Path(result["outputs"][0]["path"]), 0.5)
        padded_top_row = frames[("pad", "center")][:160 * 3]
        self.assertLess(max(padded_top_row), 5)
        self.assertGreater(max(frames[("crop", "left")][:160 * 3]), 100)
        self.assertNotEqual(frames[("crop", "left")], frames[("crop", "right")])

    def test_youtube_boundary_disables_config_and_playlist_and_retains_source(self):
        # Only the external download is replaced; copying, probing and hashing are real.
        actual_run = subprocess.run
        def download_boundary(command, **kwargs):
            if "--ignore-config" not in command:
                return actual_run(command, **kwargs)
            self.assertIn("--no-playlist", command)
            self.assertTrue(Path(command[command.index("--ffmpeg-location") + 1]).is_file(), "yt-dlp needs a resolved FFmpeg file or directory")
            self.assertEqual(command[-2:], ["--", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
            self.assertNotIn("shell", kwargs)
            shutil.copyfile(self.landscape, Path(kwargs["cwd"]) / "source.mp4")
            return subprocess.CompletedProcess(command, 0, b"source.mp4\n")
        with patch("clipear.media.subprocess.run", side_effect=download_boundary):
            imported = self.media.ingest("https://youtu.be/dQw4w9WgXcQ?list=playlist", self.work)
        self.assertEqual(imported["sha256"], hashlib.sha256(self.landscape.read_bytes()).hexdigest())
        self.assertTrue(list(self.work.glob("download-*.log")))

    def test_whisper_boundary_receives_real_audio_and_preserves_json_evidence(self):
        # A model is deliberately not downloaded; replace the external recognizer only.
        model = self.work / "existing model.bin"
        model.write_bytes(b"fixture model placeholder")
        self.settings.whisper_cli = "fixture-whisper"
        self.settings.whisper_model = model
        actual_run = subprocess.run
        glossary = "BNB Chain; $(touch should-not-exist) ' quotes"
        def recognizer_boundary(command, **kwargs):
            if command[0] != "fixture-whisper":
                return actual_run(command, **kwargs)
            audio = Path(command[command.index("-f") + 1])
            probe = json.loads(actual_run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(audio)], capture_output=True, text=True, check=True).stdout)
            self.assertEqual(probe["streams"][0]["sample_rate"], "16000")
            self.assertEqual(probe["streams"][0]["channels"], 1)
            self.assertEqual(command[command.index("--prompt") + 1], glossary)
            output = Path(command[command.index("-of") + 1]).with_suffix(".json")
            output.write_text(json.dumps({"result": {"language": "pt"}, "transcription": [{"offsets": {"from": 250, "to": 1250}, "text": " Olá BNB Chain! "}]}))
            return subprocess.CompletedProcess(command, 0, b"recognized\n")
        with patch("clipear.media.subprocess.run", side_effect=recognizer_boundary):
            transcript = self.media.transcribe(self.landscape, self.work, "pt", glossary)
        self.assertEqual(transcript["language"], "pt")
        self.assertEqual(transcript["segments"], [{"start": 0.25, "end": 1.25, "text": "Olá BNB Chain!"}])
        self.assertTrue(Path(transcript["path"]).is_file())
        self.assertTrue(list(self.work.glob("transcribe-*.log")))
        self.assertFalse((self.work / "should-not-exist").exists())

    def test_distinct_clip_and_profile_ids_cannot_overwrite_each_others_outputs(self):
        plan = self.plan(clips=[{"id": "a-b", "start": 0.35, "end": 0.65}, {"id": "a", "start": 1.35, "end": 1.65}],
                         outputs=[{"name": "c", "ratio": "source", "height": 90, "fit": "pad", "position": "center"},
                                  {"name": "b-c", "ratio": "source", "height": 90, "fit": "pad", "position": "center"}])
        result = self.media.render(self.landscape, self.work, plan, [])
        self.assertEqual(len({item["path"] for item in result["outputs"]}), 4)
        previews = self.media.preview(self.landscape, self.work, plan)
        self.assertEqual(len({item["path"] for item in previews}), 4)

    def test_source_framing_converts_anamorphic_pixels_without_adding_bars(self):
        anamorphic = self.work / "anamorphic.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:size=160x90:rate=30:duration=2",
                        "-vf", "setsar=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(anamorphic)], check=True, capture_output=True)
        plan = self.plan(source_sha256=hashlib.sha256(anamorphic.read_bytes()).hexdigest())
        result = self.media.render(anamorphic, self.work / "square-pixels", plan, [])
        video = result["outputs"][0]
        self.assertEqual((video["probe"]["width"], video["probe"]["height"]), (320, 90))
        frame = self.raw_frame(Path(video["path"]))
        self.assertGreater(frame[0], 200, "source framing must fill the full image with the original red content")
        self.assertLess(frame[1], 15)

    def test_local_playlists_cannot_read_video_outside_input_roots(self):
        outside = self.root / "outside.mp4"
        shutil.copyfile(self.landscape, outside)
        playlist = self.work / "camera.m3u8"
        playlist.write_text("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:4.0,\n../../outside.mp4\n#EXT-X-ENDLIST\n")
        self.settings.input_roots = (self.work,)
        with self.assertRaisesRegex(MediaError, "format|Format|inspect|Inspect"):
            self.media.ingest(str(playlist), self.work / "imported")


if __name__ == "__main__":
    unittest.main()
