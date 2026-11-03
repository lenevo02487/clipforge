"""Core ffmpeg command building + running for clipforge.

Everything here is pure stdlib. The only external requirement is the
`ffmpeg` / `ffprobe` binaries, which most systems already have.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class ClipforgeError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise ClipforgeError(
                f"'{tool}' not found on PATH. Install ffmpeg: "
                "https://ffmpeg.org/download.html"
            )


def parse_timestamp(value: str | float | int) -> float:
    """Parse '90', '1:30', '01:30.5' or a number into seconds (float)."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if not text:
            raise ClipforgeError("Empty timestamp")
        if re.fullmatch(r"\d+(\.\d+)?", text):
            seconds = float(text)
        else:
            parts = text.split(":")
            if len(parts) not in (2, 3) or not all(
                re.fullmatch(r"\d+(\.\d+)?", p) for p in parts
            ):
                raise ClipforgeError(f"Cannot parse timestamp: {value!r}")
            nums = [float(p) for p in parts]
            seconds = nums[0] * 60 + nums[1] if len(nums) == 2 else (
                nums[0] * 3600 + nums[1] * 60 + nums[2]
            )
    if seconds < 0:
        raise ClipforgeError(f"Timestamp cannot be negative: {value!r}")
    return seconds


def probe(path: str | Path) -> dict:
    """Return ffprobe info: {'width': int, 'height': int, 'duration': float}."""
    require_ffmpeg()
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise ClipforgeError(f"ffprobe failed on {path}: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout)
    streams = data.get("streams") or [{}]
    return {
        "width": int(streams[0].get("width", 0)),
        "height": int(streams[0].get("height", 0)),
        "duration": float(data.get("format", {}).get("duration", 0.0)),
    }


@dataclass
class ClipSpec:
    start: float
    duration: float
    out: Path
    width: int = 1080
    height: int = 1920
    mode: str = "crop"            # "crop" (center crop) or "pad" (blurred bg fill)
    logo: Path | None = None
    logo_seconds: float = 6.0
    logo_width: int = 380
    captions: Path | None = None  # .srt burned in, times relative to full video
    loudnorm: bool = False
    crf: int = 19
    fps: int | None = None
    extra_video_filters: list[str] = field(default_factory=list)


def _escape_filter_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def build_filter(spec: ClipSpec, src_w: int, src_h: int) -> str:
    """Build the -filter_complex graph for one clip."""
    w, h = spec.width, spec.height
    if spec.mode == "crop":
        # Scale so the frame covers the target, then center-crop.
        base = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},setsar=1"
        )
    elif spec.mode == "pad":
        base = (
            f"[0:v]split[a][b];"
            f"[a]scale={w}:{h}:flags=lanczos,gblur=sigma=40,eq=brightness=-0.15[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    else:
        raise ClipforgeError(f"Unknown mode {spec.mode!r} (use 'crop' or 'pad')")

    steps = [base + "[vbase]"]
    current = "vbase"

    if spec.captions is not None:
        steps.append(
            f"[{current}]subtitles='{_escape_filter_path(spec.captions)}'"
            f":force_style='FontSize=22,PrimaryColour=&HFFFFFF&,"
            f"OutlineColour=&H80000000&,BorderStyle=1,Outline=2,MarginV=140'[vsub]"
        )
        current = "vsub"

    if spec.extra_video_filters:
        joined = ",".join(spec.extra_video_filters)
        steps.append(f"[{current}]{joined}[vextra]")
        current = "vextra"

    if spec.logo is not None:
        # Logo input is index 1 when captions file is not an input; ffmpeg
        # inputs: 0 = video, 1 = logo image.
        steps.append(f"[1:v]scale={spec.logo_width}:-1[logo]")
        steps.append(
            f"[{current}][logo]overlay=(W-w)/2:24:"
            f"enable='between(t,0,{spec.logo_seconds})'[vout]"
        )
        current = "vout"
    else:
        steps.append(f"[{current}]null[vout]")

    return ";".join(steps)


def build_command(src: Path, spec: ClipSpec, src_w: int, src_h: int) -> list[str]:
    # NOTE: -ss is used on the OUTPUT side so burned-in subtitles keep the
    # full video's timestamps (input-side seeking would shift them).
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if spec.logo is not None:
        cmd += ["-i", str(spec.logo)]
    cmd += [
        "-ss", f"{spec.start:.3f}",
        "-t", f"{spec.duration:.3f}",
        "-filter_complex", build_filter(spec, src_w, src_h),
        "-map", "[vout]",
        "-map", "0:a?",
    ]
    if spec.fps:
        cmd += ["-r", str(spec.fps)]
    if spec.loudnorm:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(spec.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(spec.out),
    ]
    return cmd


def make_clip(src: str | Path, spec: ClipSpec) -> Path:
    require_ffmpeg()
    src = Path(src)
    if not src.exists():
        raise ClipforgeError(f"Input not found: {src}")
    spec.out.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    if info["duration"] and spec.start >= info["duration"]:
        raise ClipforgeError(
            f"Start {spec.start}s is beyond the video length {info['duration']:.1f}s"
        )
    cmd = build_command(src, spec, info["width"], info["height"])
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0 or not spec.out.exists():
        tail = "\n".join(run.stderr.splitlines()[-8:])
        raise ClipforgeError(f"ffmpeg failed:\n{tail}")
    return spec.out


def parse_segments_file(path: str | Path) -> list[tuple[float, float, str]]:
    """Parse a batch segments file.

    One clip per line:  <start> <duration> [name]
    Timestamps may be seconds (90, 90.5) or mm:ss / hh:mm:ss.
    Blank lines and lines starting with # are ignored.
    """
    clips: list[tuple[float, float, str]] = []
    for lineno, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ClipforgeError(f"{path}:{lineno}: need at least start and duration")
        start = parse_timestamp(parts[0])
        duration = parse_timestamp(parts[1])
        if duration <= 0:
            raise ClipforgeError(f"{path}:{lineno}: duration must be > 0")
        name = parts[2] if len(parts) > 2 else f"clip_{len(clips) + 1:02d}"
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ClipforgeError(f"{path}:{lineno}: bad clip name {name!r}")
        clips.append((start, duration, name))
    if not clips:
        raise ClipforgeError(f"No clips found in {path}")
    return clips
