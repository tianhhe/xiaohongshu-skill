"""
Video maker for Xiaohongshu posts.

Creates slideshow-style videos from images with text overlays and background
music using ffmpeg. Designed for XHS vertical format (1080x1440, 3:4 ratio).

Requirements:
    - ffmpeg must be installed and in PATH

CLI usage:
    python video_maker.py slideshow \
        --images img1.jpg img2.jpg img3.jpg \
        --texts "第一页文字" "第二页文字" "第三页文字" \
        --output /tmp/video.mp4

    python video_maker.py slideshow \
        --images img1.jpg img2.jpg \
        --texts "文字1" "文字2" \
        --music /path/to/bgm.mp3 \
        --duration-per-image 4 \
        --output /tmp/video.mp4
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# XHS recommended vertical video specs
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1440  # 3:4 aspect ratio
VIDEO_FPS = 30
DEFAULT_DURATION_PER_IMAGE = 3  # seconds
DEFAULT_OUTPUT_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "tmp", "generated_videos")
)


class VideoMakerError(Exception):
    """Error during video creation."""


def _check_ffmpeg() -> str:
    """Check if ffmpeg is available and return its path."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoMakerError(
            "ffmpeg not found. Install it with:\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg\n"
            "  Windows: winget install ffmpeg"
        )
    return ffmpeg


def _run_ffmpeg(args: list[str], description: str = "") -> subprocess.CompletedProcess:
    """Run an ffmpeg command with error handling."""
    ffmpeg = _check_ffmpeg()
    cmd = [ffmpeg] + args
    desc = description or " ".join(cmd[:5])
    print(f"[video_maker] Running: {desc}...")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5 minute timeout
    )
    if result.returncode != 0:
        stderr = result.stderr[-500:] if result.stderr else "No error output"
        raise VideoMakerError(f"ffmpeg failed: {stderr}")
    return result


def _prepare_image_for_video(
    image_path: str,
    output_path: str,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> str:
    """Resize and pad an image to exact video dimensions.

    Uses ffmpeg to scale the image to fit within the frame while maintaining
    aspect ratio, then pads with black to exact dimensions.
    """
    _run_ffmpeg(
        [
            "-y", "-i", image_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-q:v", "2",
            output_path,
        ],
        description=f"Preparing image {os.path.basename(image_path)}",
    )
    return output_path


def _create_text_overlay_image(
    text: str,
    output_path: str,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    font_size: int = 48,
    font_color: str = "white",
    bg_opacity: float = 0.5,
) -> str:
    """Create a transparent PNG with text overlay using ffmpeg.

    The text is rendered at the bottom of the frame with a semi-transparent
    background bar.
    """
    if not text.strip():
        # Create a fully transparent image (no text)
        _run_ffmpeg(
            [
                "-y",
                "-f", "lavfi",
                "-i", f"color=c=black@0.0:s={width}x{height}:d=1",
                "-vframes", "1",
                "-pix_fmt", "argb",
                output_path,
            ],
            description="Creating empty overlay",
        )
        return output_path

    # Escape text for ffmpeg drawtext filter
    escaped_text = (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "%%")
    )

    # Build a drawtext filter with background box
    drawtext_filter = (
        f"drawtext=text='{escaped_text}'"
        f":fontsize={font_size}"
        f":fontcolor={font_color}"
        f":x=(w-text_w)/2"
        f":y=h-text_h-80"
        f":box=1"
        f":boxcolor=black@{bg_opacity}"
        f":boxborderw=20"
    )

    _run_ffmpeg(
        [
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black@0.0:s={width}x{height}:d=1",
            "-vf", drawtext_filter,
            "-vframes", "1",
            "-pix_fmt", "argb",
            output_path,
        ],
        description=f"Creating text overlay: {text[:30]}",
    )
    return output_path


def make_slideshow_video(
    images: list[str],
    texts: list[str] | None = None,
    music_path: str | None = None,
    output_path: str | None = None,
    duration_per_image: float = DEFAULT_DURATION_PER_IMAGE,
    transition: str = "fade",
    transition_duration: float = 0.5,
) -> dict[str, Any]:
    """Create a slideshow video from images with optional text and music.

    Args:
        images: List of image file paths.
        texts: Optional list of text overlays (one per image).
            Can be shorter than images; missing entries default to "".
        music_path: Optional background music file path.
        output_path: Output video file path. Auto-generated if None.
        duration_per_image: Seconds to show each image (default: 3).
        transition: Transition type ("fade" or "none").
        transition_duration: Duration of transition in seconds.

    Returns:
        {"success": True, "path": "/abs/path/video.mp4", "duration": N,
         "image_count": M, "resolution": "1080x1440"}
    """
    if not images:
        raise VideoMakerError("At least one image is required.")

    _check_ffmpeg()

    # Validate image files
    for img in images:
        if not os.path.isfile(img):
            raise VideoMakerError(f"Image not found: {img}")

    # Prepare output path
    if not output_path:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, f"slideshow_{timestamp}.mp4")

    abs_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)

    # Normalize texts list
    if texts is None:
        texts = [""] * len(images)
    while len(texts) < len(images):
        texts.append("")

    total_duration = len(images) * duration_per_image

    with tempfile.TemporaryDirectory(prefix="xhs_video_") as tmpdir:
        # Step 1: Prepare each image (resize + pad to exact video dimensions)
        prepared_images = []
        for i, img in enumerate(images):
            prepared = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
            _prepare_image_for_video(img, prepared)
            prepared_images.append(prepared)

        # Step 2: Build ffmpeg complex filter for slideshow
        # Create a concat file for sequential playback
        concat_file = os.path.join(tmpdir, "concat.txt")
        with open(concat_file, "w") as f:
            for i, img in enumerate(prepared_images):
                f.write(f"file '{img}'\n")
                f.write(f"duration {duration_per_image}\n")
            # ffmpeg concat demuxer requires the last file entry twice
            f.write(f"file '{prepared_images[-1]}'\n")

        # Step 3: Build ffmpeg command
        cmd = [
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
        ]

        # Build text overlay filter chain
        text_filters = []
        for i, text in enumerate(texts):
            if not text.strip():
                continue
            escaped = (
                text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "\\'")
                .replace("%", "%%")
            )
            start_time = i * duration_per_image
            end_time = start_time + duration_per_image
            text_filters.append(
                f"drawtext=text='{escaped}'"
                f":fontsize=48"
                f":fontcolor=white"
                f":x=(w-text_w)/2"
                f":y=h-text_h-80"
                f":box=1"
                f":boxcolor=black@0.5"
                f":boxborderw=20"
                f":enable='between(t,{start_time},{end_time})'"
            )

        # Video filter
        vf_parts = [f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                     f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
                     f"fps={VIDEO_FPS},"
                     f"format=yuv420p"]

        if text_filters:
            vf_parts.extend(text_filters)

        vf = ",".join(vf_parts)
        cmd.extend(["-vf", vf])

        # Add background music if provided
        if music_path and os.path.isfile(music_path):
            cmd.extend(["-i", music_path])
            cmd.extend([
                "-map", "0:v",
                "-map", "1:a",
                "-shortest",
                "-c:a", "aac",
                "-b:a", "128k",
            ])
        else:
            # Silent audio track (some platforms require audio)
            cmd.extend([
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                "-map", "0:v",
                "-map", "1:a",
                "-shortest",
                "-c:a", "aac",
                "-b:a", "32k",
            ])

        # Output codec settings
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-movflags", "+faststart",
            "-t", str(total_duration),
            abs_output,
        ])

        _run_ffmpeg(cmd, description="Creating slideshow video")

    # Verify output
    if not os.path.isfile(abs_output):
        raise VideoMakerError(f"Output video not created: {abs_output}")

    file_size = os.path.getsize(abs_output)
    print(f"[video_maker] Video created: {abs_output} ({file_size / 1024 / 1024:.1f} MB)")

    return {
        "success": True,
        "path": abs_output,
        "duration": total_duration,
        "image_count": len(images),
        "resolution": f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}",
        "size_bytes": file_size,
        "has_music": bool(music_path and os.path.isfile(music_path)),
    }


# ---- CLI ----

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Video Maker for XHS posts")
    sub = parser.add_subparsers(dest="command", required=True)

    p_slide = sub.add_parser("slideshow", help="Create slideshow video from images")
    p_slide.add_argument("--images", nargs="+", required=True, help="Image file paths")
    p_slide.add_argument("--texts", nargs="+", help="Text overlays per image")
    p_slide.add_argument("--music", help="Background music file path")
    p_slide.add_argument("--output", help="Output video file path")
    p_slide.add_argument(
        "--duration-per-image", type=float, default=DEFAULT_DURATION_PER_IMAGE,
        help=f"Seconds per image (default: {DEFAULT_DURATION_PER_IMAGE})"
    )

    p_check = sub.add_parser("check", help="Check if ffmpeg is available")

    args = parser.parse_args()

    if args.command == "check":
        try:
            ffmpeg = _check_ffmpeg()
            version = subprocess.run(
                [ffmpeg, "-version"], capture_output=True, text=True
            )
            first_line = version.stdout.split("\n")[0] if version.stdout else "unknown"
            print(json.dumps({"available": True, "path": ffmpeg, "version": first_line}))
        except VideoMakerError as e:
            print(json.dumps({"available": False, "error": str(e)}))

    elif args.command == "slideshow":
        result = make_slideshow_video(
            images=args.images,
            texts=args.texts,
            music_path=args.music,
            output_path=args.output,
            duration_per_image=args.duration_per_image,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
