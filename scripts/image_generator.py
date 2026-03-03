"""
AI image generation for Xiaohongshu posts.

Supports Aliyun (DashScope) image generation API.
API credentials are read from config/persona.json.

CLI usage:
    python image_generator.py generate --prompt "描述" --output /tmp/img.png
    python image_generator.py batch --prompts "描述1" "描述2" --output-dir /tmp/images/
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from persona_manager import get_image_api_config

# Default temp directory for generated images
DEFAULT_OUTPUT_DIR = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "tmp", "generated_images")
)


class ImageGeneratorError(Exception):
    """Error during image generation."""


def _ensure_requests():
    """Import requests lazily."""
    try:
        import requests
        return requests
    except ImportError:
        raise ImageGeneratorError(
            "requests library is required. Install with: pip install requests"
        )


def generate_image_aliyun(
    prompt: str,
    api_key: str,
    model: str = "wanx-v1",
    endpoint: str = "",
    size: str = "1024*1024",
    style: str = "",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate an image using Aliyun DashScope API.

    Args:
        prompt: Image description in Chinese or English.
        api_key: Aliyun DashScope API key.
        model: Model name (default: wanx-v1).
        endpoint: API endpoint override (optional).
        size: Image size, e.g. "1024*1024".
        style: Style tag (optional, depends on model).
        output_path: Where to save the image. Auto-generated if None.

    Returns:
        {"success": True, "path": "/abs/path/image.png", "url": "...", "task_id": "..."}
    """
    requests = _ensure_requests()

    if not api_key:
        raise ImageGeneratorError(
            "Aliyun API key not configured. "
            "Update config/persona.json -> image_api.api_key"
        )

    # Default DashScope endpoint
    if not endpoint:
        endpoint = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    body: dict[str, Any] = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": 1},
    }
    if style:
        body["parameters"]["style"] = style

    # Step 1: Submit task
    print(f"[image_generator] Submitting image task: {prompt[:50]}...")
    resp = requests.post(endpoint, headers=headers, json=body, timeout=30)
    if resp.status_code != 200:
        raise ImageGeneratorError(
            f"Aliyun API error {resp.status_code}: {resp.text[:200]}"
        )

    result = resp.json()
    task_id = result.get("output", {}).get("task_id")
    if not task_id:
        # Synchronous mode — image may be directly in response
        image_url = (
            result.get("output", {}).get("results", [{}])[0].get("url", "")
        )
        if image_url:
            return _download_and_save(requests, image_url, output_path, task_id="sync")
        raise ImageGeneratorError(f"No task_id in response: {json.dumps(result, ensure_ascii=False)[:300]}")

    # Step 2: Poll for completion
    task_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    poll_headers = {"Authorization": f"Bearer {api_key}"}

    print(f"[image_generator] Task submitted: {task_id}. Polling...")
    for attempt in range(60):  # Max 5 minutes
        time.sleep(5)
        poll_resp = requests.get(task_url, headers=poll_headers, timeout=15)
        if poll_resp.status_code != 200:
            continue
        poll_result = poll_resp.json()
        status = poll_result.get("output", {}).get("task_status", "")

        if status == "SUCCEEDED":
            results = poll_result.get("output", {}).get("results", [])
            if results:
                image_url = results[0].get("url", "")
                if image_url:
                    return _download_and_save(requests, image_url, output_path, task_id)
            raise ImageGeneratorError("Task succeeded but no image URL found.")

        elif status in ("FAILED", "CANCELED"):
            msg = poll_result.get("output", {}).get("message", "Unknown error")
            raise ImageGeneratorError(f"Image generation failed: {msg}")

        elif status in ("PENDING", "RUNNING"):
            if attempt % 6 == 0:
                print(f"[image_generator] Still generating... ({attempt * 5}s)")
            continue

    raise ImageGeneratorError("Image generation timed out after 5 minutes.")


def _download_and_save(
    requests, image_url: str, output_path: str | None, task_id: str
) -> dict[str, Any]:
    """Download an image from URL and save to disk."""
    if not output_path:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, f"gen_{timestamp}.png")

    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    print(f"[image_generator] Downloading image to {abs_path}...")
    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()

    with open(abs_path, "wb") as f:
        f.write(img_resp.content)

    print(f"[image_generator] Image saved: {abs_path}")
    return {
        "success": True,
        "path": abs_path,
        "url": image_url,
        "task_id": task_id,
        "size_bytes": len(img_resp.content),
    }


def generate_image(
    prompt: str,
    style: str = "",
    output_path: str | None = None,
    size: str = "1024*1024",
    persona_config_path: str | None = None,
) -> dict[str, Any]:
    """Generate an image using the configured API provider.

    Reads API config from persona.json. Currently supports Aliyun.

    Args:
        prompt: Image description.
        style: Style tag (optional).
        output_path: Where to save. Auto-generated if None.
        size: Image dimensions.
        persona_config_path: Override persona config path.

    Returns:
        {"success": True, "path": "...", "url": "...", "task_id": "..."}
    """
    config = get_image_api_config(persona_config_path)
    provider = config.get("provider", "aliyun").lower()

    if provider == "aliyun":
        return generate_image_aliyun(
            prompt=prompt,
            api_key=config.get("api_key", ""),
            model=config.get("model", "wanx-v1"),
            endpoint=config.get("endpoint", ""),
            size=size,
            style=style,
            output_path=output_path,
        )
    else:
        raise ImageGeneratorError(f"Unsupported image provider: {provider}")


def generate_images_for_post(
    title: str,
    content: str,
    count: int = 3,
    style: str = "",
    persona_config_path: str | None = None,
) -> list[dict[str, Any]]:
    """Generate multiple images for a Xiaohongshu post.

    Creates `count` images with prompts derived from the post content.

    Args:
        title: Post title.
        content: Post body text.
        count: Number of images to generate (default: 3).
        style: Style tag.
        persona_config_path: Override persona config path.

    Returns:
        List of result dicts from generate_image().
    """
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    results = []
    for i in range(count):
        # Generate varied prompts based on position
        if i == 0:
            prompt = f"小红书封面图: {title}。风格精美，适合社交媒体分享。"
        else:
            prompt = f"配图{i + 1}: {content[:100]}。补充说明图，风格统一。"

        output_path = os.path.join(
            DEFAULT_OUTPUT_DIR, f"post_{timestamp}_{i + 1}.png"
        )

        try:
            result = generate_image(
                prompt=prompt,
                style=style,
                output_path=output_path,
                persona_config_path=persona_config_path,
            )
            results.append(result)
        except ImageGeneratorError as e:
            print(f"[image_generator] Warning: Image {i + 1} failed: {e}")
            results.append({"success": False, "error": str(e), "index": i + 1})

    return results


# ---- CLI ----

def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI Image Generator for XHS")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Generate a single image")
    p_gen.add_argument("--prompt", required=True, help="Image description")
    p_gen.add_argument("--output", help="Output file path")
    p_gen.add_argument("--style", default="", help="Style tag")
    p_gen.add_argument("--size", default="1024*1024", help="Size (default: 1024*1024)")

    p_batch = sub.add_parser("batch", help="Generate multiple images")
    p_batch.add_argument("--prompts", nargs="+", required=True, help="Image descriptions")
    p_batch.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    p_batch.add_argument("--style", default="", help="Style tag")

    p_post = sub.add_parser("for-post", help="Generate images for a post")
    p_post.add_argument("--title", required=True, help="Post title")
    p_post.add_argument("--content", required=True, help="Post content")
    p_post.add_argument("--count", type=int, default=3, help="Number of images")
    p_post.add_argument("--style", default="", help="Style tag")

    args = parser.parse_args()

    if args.command == "generate":
        result = generate_image(
            prompt=args.prompt,
            style=args.style,
            output_path=args.output,
            size=args.size,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "batch":
        os.makedirs(args.output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results = []
        for i, prompt in enumerate(args.prompts):
            output = os.path.join(args.output_dir, f"batch_{timestamp}_{i + 1}.png")
            result = generate_image(
                prompt=prompt, style=args.style, output_path=output
            )
            results.append(result)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif args.command == "for-post":
        results = generate_images_for_post(
            title=args.title,
            content=args.content,
            count=args.count,
            style=args.style,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
