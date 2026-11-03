"""clipforge command line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import (
    ClipSpec,
    ClipforgeError,
    make_clip,
    parse_segments_file,
    parse_timestamp,
)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--width", type=int, default=1080, help="Output width (default 1080)")
    p.add_argument("--height", type=int, default=1920, help="Output height (default 1920)")
    p.add_argument("--mode", choices=["crop", "pad"], default="crop",
                   help="crop = center crop to fill frame; pad = blurred background fill")
    p.add_argument("--logo", type=Path, help="Logo/brand image overlaid at the top")
    p.add_argument("--logo-seconds", type=float, default=6.0,
                   help="How long the logo stays on screen (default 6)")
    p.add_argument("--logo-width", type=int, default=380, help="Logo width in px (default 380)")
    p.add_argument("--captions", type=Path, help="SRT file (times of the FULL video) to burn in")
    p.add_argument("--loudnorm", action="store_true",
                   help="Normalize audio loudness (good for Shorts/Reels)")
    p.add_argument("--crf", type=int, default=19, help="x264 quality, lower = better (default 19)")
    p.add_argument("--fps", type=int, help="Force output frame rate")


def _spec_from_args(args, start, duration, out) -> ClipSpec:
    return ClipSpec(
        start=start, duration=duration, out=out,
        width=args.width, height=args.height, mode=args.mode,
        logo=args.logo, logo_seconds=args.logo_seconds, logo_width=args.logo_width,
        captions=args.captions, loudnorm=args.loudnorm, crf=args.crf, fps=args.fps,
    )


def cmd_make(args) -> int:
    out = args.out or Path(args.video).with_suffix("").with_name(
        Path(args.video).stem + "_clip.mp4"
    )
    spec = _spec_from_args(args, parse_timestamp(args.start), parse_timestamp(args.duration), out)
    result = make_clip(args.video, spec)
    print(f"OK  {result}")
    return 0


def cmd_batch(args) -> int:
    clips = parse_segments_file(args.segments)
    outdir = args.outdir or Path("clips")
    done = 0
    for start, duration, name in clips:
        out = outdir / f"{name}.mp4"
        spec = _spec_from_args(args, start, duration, out)
        make_clip(args.video, spec)
        print(f"OK  {out}  ({duration:.0f}s from {start:.0f}s)")
        done += 1
    print(f"Done: {done} clip(s) in {outdir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clipforge",
        description="Turn long videos into platform-ready vertical Shorts/Reels. "
                    "No AI, no API keys, no watermarks — just ffmpeg.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_make = sub.add_parser("make", help="Make one vertical clip")
    p_make.add_argument("video")
    p_make.add_argument("--start", required=True, help="Start time: seconds or mm:ss")
    p_make.add_argument("--duration", required=True, help="Clip length: seconds or mm:ss")
    p_make.add_argument("--out", type=Path, help="Output file (default <video>_clip.mp4)")
    _add_common(p_make)
    p_make.set_defaults(func=cmd_make)

    p_batch = sub.add_parser("batch", help="Make many clips from a segments file")
    p_batch.add_argument("video")
    p_batch.add_argument("segments", help="Text file: '<start> <duration> [name]' per line")
    p_batch.add_argument("--outdir", type=Path, help="Output directory (default ./clips)")
    _add_common(p_batch)
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ClipforgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
