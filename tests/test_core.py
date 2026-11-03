import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipforge.core import (
    ClipSpec,
    ClipforgeError,
    build_command,
    build_filter,
    make_clip,
    parse_segments_file,
    parse_timestamp,
    probe,
)


class TestParseTimestamp(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(parse_timestamp("90"), 90.0)
        self.assertEqual(parse_timestamp("90.5"), 90.5)
        self.assertEqual(parse_timestamp(42), 42.0)

    def test_mm_ss(self):
        self.assertEqual(parse_timestamp("1:30"), 90.0)
        self.assertEqual(parse_timestamp("01:30.5"), 90.5)

    def test_hh_mm_ss(self):
        self.assertEqual(parse_timestamp("1:02:03"), 3723.0)

    def test_invalid(self):
        for bad in ("", "abc", "1:2:3:4", "-5"):
            with self.assertRaises(ClipforgeError):
                parse_timestamp(bad)


class TestSegmentsFile(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "segs.txt"
            f.write_text("# comment\n50 28 hook\n1:35 0:30 finisher\n\n90 20\n")
            clips = parse_segments_file(f)
            self.assertEqual(clips[0], (50.0, 28.0, "hook"))
            self.assertEqual(clips[1], (95.0, 30.0, "finisher"))
            self.assertEqual(clips[2], (90.0, 20.0, "clip_03"))

    def test_bad_duration(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "segs.txt"
            f.write_text("10 0 nope\n")
            with self.assertRaises(ClipforgeError):
                parse_segments_file(f)


class TestFilterBuilding(unittest.TestCase):
    def test_crop_graph(self):
        spec = ClipSpec(start=0, duration=5, out=Path("o.mp4"))
        graph = build_filter(spec, 1280, 720)
        self.assertIn("crop=1080:1920", graph)
        self.assertIn("[vout]", graph)

    def test_pad_graph(self):
        spec = ClipSpec(start=0, duration=5, out=Path("o.mp4"), mode="pad")
        graph = build_filter(spec, 1280, 720)
        self.assertIn("gblur", graph)

    def test_logo_overlay_window(self):
        spec = ClipSpec(start=0, duration=5, out=Path("o.mp4"),
                        logo=Path("logo.png"), logo_seconds=6)
        graph = build_filter(spec, 1280, 720)
        self.assertIn("between(t,0,6", graph)
        cmd = build_command(Path("in.mp4"), spec, 1280, 720)
        self.assertEqual(cmd.count("-i"), 2)

    def test_bad_mode(self):
        spec = ClipSpec(start=0, duration=5, out=Path("o.mp4"), mode="weird")
        with self.assertRaises(ClipforgeError):
            build_filter(spec, 1280, 720)


class TestEndToEnd(unittest.TestCase):
    """Real ffmpeg run on a tiny generated video."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.src = d / "src.mp4"
        # 10s, 640x360 test pattern with a beep track
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=30:duration=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(cls.src)],
            check=True, capture_output=True,
        )
        cls.logo = d / "logo.png"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=orange:size=400x120:duration=0.1",
             "-frames:v", "1", str(cls.logo)],
            check=True, capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_make_clip_vertical_with_logo(self):
        out = Path(self.tmp.name) / "out.mp4"
        spec = ClipSpec(start=2, duration=3, out=out,
                        width=270, height=480,
                        logo=self.logo, logo_seconds=2, logo_width=120)
        result = make_clip(self.src, spec)
        self.assertTrue(result.exists())
        info = probe(result)
        self.assertEqual((info["width"], info["height"]), (270, 480))
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.4)

    def test_make_clip_pad_mode(self):
        out = Path(self.tmp.name) / "out_pad.mp4"
        spec = ClipSpec(start=0, duration=2, out=out,
                        width=270, height=480, mode="pad")
        make_clip(self.src, spec)
        info = probe(out)
        self.assertEqual((info["width"], info["height"]), (270, 480))

    def test_start_beyond_end_errors(self):
        spec = ClipSpec(start=999, duration=2,
                        out=Path(self.tmp.name) / "x.mp4")
        with self.assertRaises(ClipforgeError):
            make_clip(self.src, spec)


if __name__ == "__main__":
    unittest.main()
