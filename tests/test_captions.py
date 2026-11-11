"""Caption behavior: timestamps and text are editorial data, never filter code."""
import tempfile
import unittest
from pathlib import Path

try:
    from clipear.captions import remap_cues, write_ass, write_srt
except ImportError:
    remap_cues = write_ass = write_srt = None


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(remap_cues, "caption timeline mapping is not implemented")

    def test_intersects_source_cues_and_retimes_both_edges(self):
        result = remap_cues([
            {"start": 1.0, "end": 4.0, "text": "First words"},
            {"start": 5.0, "end": 8.0, "text": "Last words"},
            {"start": 8.0, "end": 9.0, "text": "Outside"},
        ], 2.0, 6.0, 2.0)
        self.assertEqual(result["cues"], [
            {"start": 0.0, "end": 1.0, "text": "First words"},
            {"start": 1.5, "end": 2.0, "text": "Last words"},
        ])

    def test_wraps_without_dropping_words_and_surfaces_unreadable_cues(self):
        text = "A deliberately very long sentence contains every original word even when its timing is too short."
        result = remap_cues([{"start": 0, "end": 0.2, "text": text}], 0, 1)
        self.assertEqual(" ".join(result["cues"][0]["text"].split()), text)
        self.assertTrue(all(len(line) <= 42 for line in result["cues"][0]["text"].splitlines()))
        self.assertIn("reading_speed", [item["code"] for item in result["warnings"]])
        self.assertIn("short_duration", [item["code"] for item in result["warnings"]])
        self.assertIn("too_many_lines", [item["code"] for item in result["warnings"]])

    def test_partial_cues_warn_even_when_text_is_readable(self):
        cue = {"start": 1, "end": 6, "text": "One complete sentence."}
        for start, end in ((2, 5), (2, 6), (1, 5)):
            with self.subTest(start=start, end=end):
                result = remap_cues([cue], start, end)
                self.assertEqual(result["cues"][0]["text"], cue["text"])
                conflicts = [warning for warning in result["warnings"] if warning["code"] == "boundary_conflict"]
                self.assertEqual(len(conflicts), 1)
                self.assertEqual((conflicts[0]["source_start"], conflicts[0]["source_end"]), (1, 6))
                self.assertEqual((conflicts[0]["clip_start"], conflicts[0]["clip_end"]), (start, end))

    def test_complete_or_outside_cues_have_no_boundary_conflict(self):
        result = remap_cues([
            {"start": 0, "end": 2, "text": "Before"},
            {"start": 2, "end": 5, "text": "Inside"},
            {"start": 5, "end": 6, "text": "After"},
        ], 2, 5, 2)
        self.assertEqual(result["cues"], [{"start": 0, "end": 1.5, "text": "Inside"}])
        self.assertEqual(result["warnings"], [])

    def test_rejects_invalid_timelines_and_blank_text(self):
        for cue in [
            {"start": float("nan"), "end": 2, "text": "x"},
            {"start": 2, "end": 1, "text": "x"},
            {"start": -1, "end": 1, "text": "x"},
            {"start": 0, "end": 1, "text": "   "},
        ]:
            with self.subTest(cue=cue), self.assertRaises(ValueError):
                remap_cues([cue], 0, 3)
        with self.assertRaises(ValueError):
            remap_cues([], 0, 3, float("inf"))

    def test_srt_rounds_to_milliseconds_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cues.srt"
            write_srt(path, [{"start": 0.0001, "end": 61.9996, "text": "Olá, BNB Chain!\nSecond line"}])
            self.assertEqual(path.read_text(encoding="utf-8"), "1\n00:00:00,000 --> 00:01:02,000\nOlá, BNB Chain!\nSecond line\n\n")

    def test_burn_caption_size_tracks_short_edge_for_portrait_and_landscape(self):
        with tempfile.TemporaryDirectory() as temporary:
            sizes = []
            for width, height in ((1920, 1080), (1080, 1920)):
                path = Path(temporary) / f"{width}-{height}.ass"
                write_ass(path, [{"start": 0, "end": 1, "text": "Readable captions"}], width, height)
                style = next(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("Style:"))
                sizes.append(int(style.split(",")[2]))
            self.assertEqual(sizes, [52, 52])


if __name__ == "__main__":
    unittest.main()
