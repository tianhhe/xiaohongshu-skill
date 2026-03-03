"""
Persona manager for the Xiaohongshu AI agent ("digital double").

Manages loading, saving, and querying the persona configuration
that defines the agent's name, personality, interests, writing style,
and API credentials.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PERSONA_FILE = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "config", "persona.json")
)


def load_persona(path: str | None = None) -> dict[str, Any]:
    """Load persona configuration from JSON file.

    Args:
        path: Path to persona.json. Defaults to config/persona.json.

    Returns:
        Persona dict. Empty-ish defaults if file doesn't exist or is invalid.
    """
    filepath = path or DEFAULT_PERSONA_FILE
    if not os.path.isfile(filepath):
        return _default_persona()
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError):
        return _default_persona()


def save_persona(data: dict[str, Any], path: str | None = None) -> str:
    """Save persona configuration to JSON file.

    Args:
        data: Persona dict to save.
        path: Path to persona.json. Defaults to config/persona.json.

    Returns:
        Absolute path to the saved file.
    """
    filepath = path or DEFAULT_PERSONA_FILE
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return os.path.abspath(filepath)


def is_initialized(path: str | None = None) -> bool:
    """Check whether the persona has been initialized.

    Returns True only if the config exists, has initialized=true,
    and has a non-empty name.
    """
    persona = load_persona(path)
    return bool(persona.get("initialized") and persona.get("name", "").strip())


def initialize_persona(
    name: str,
    personality: str,
    tone: str,
    interests: list[str],
    writing_style: str,
    collection_folder: str | None = None,
    image_api: dict | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Create and save a new persona.

    Args:
        name: The agent's display name (e.g. "小N").
        personality: Personality description.
        tone: Tone of voice.
        interests: List of interest keywords.
        writing_style: Writing style description.
        collection_folder: Name for the agent's collection folder.
        image_api: Image generation API config dict.
        path: Path to persona.json.

    Returns:
        The saved persona dict.
    """
    persona = load_persona(path)
    persona["name"] = name.strip()
    persona["personality"] = personality.strip()
    persona["tone"] = tone.strip()
    persona["interests"] = [i.strip() for i in interests if i.strip()]
    persona["writing_style"] = writing_style.strip()
    persona["collection_folder"] = (
        collection_folder or f"{name}的收藏夹"
    ).strip()
    if image_api:
        persona["image_api"] = {**persona.get("image_api", {}), **image_api}
    persona["created_at"] = datetime.now().strftime("%Y-%m-%d")
    persona["initialized"] = True
    save_persona(persona, path)
    return persona


def update_persona(updates: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """Merge updates into the existing persona config.

    Args:
        updates: Keys to update (shallow merge).
        path: Path to persona.json.

    Returns:
        The updated persona dict.
    """
    persona = load_persona(path)
    for key, value in updates.items():
        if key == "image_api" and isinstance(value, dict):
            persona.setdefault("image_api", {}).update(value)
        elif key == "auto_behaviors" and isinstance(value, dict):
            persona.setdefault("auto_behaviors", {}).update(value)
        else:
            persona[key] = value
    save_persona(persona, path)
    return persona


def get_prompt_prefix(path: str | None = None) -> str:
    """Generate a system prompt prefix from the persona config.

    Used by SKILL.md to prepend personality context to Claude's behavior.

    Returns:
        A string like: '你是"小N"，一个活泼好奇的小红书电子分身...'
        Or empty string if not initialized.
    """
    persona = load_persona(path)
    if not persona.get("initialized") or not persona.get("name"):
        return ""

    name = persona["name"]
    parts = [f'你是"{name}"，用户的小红书电子分身。']

    if persona.get("personality"):
        parts.append(f"你的性格：{persona['personality']}。")
    if persona.get("tone"):
        parts.append(f"你的语气：{persona['tone']}。")
    if persona.get("interests"):
        parts.append(f"你感兴趣的领域：{'、'.join(persona['interests'])}。")
    if persona.get("writing_style"):
        parts.append(f"你的写作风格：{persona['writing_style']}。")
    if persona.get("collection_folder"):
        folder = persona["collection_folder"]
        parts.append(f'你的收藏夹叫做"{folder}"。')

    return " ".join(parts)


def get_image_api_config(path: str | None = None) -> dict[str, str]:
    """Get image API configuration from persona.

    Returns:
        Dict with provider, api_key, endpoint, model keys.
    """
    persona = load_persona(path)
    return persona.get("image_api", {})


def _default_persona() -> dict[str, Any]:
    """Return the default uninitialised persona structure."""
    return {
        "name": "",
        "personality": "",
        "tone": "",
        "interests": [],
        "writing_style": "",
        "collection_folder": "",
        "auto_behaviors": {
            "browse_duration_minutes": 10,
            "like_interesting": True,
            "collect_interesting": True,
            "post_feelings": True,
        },
        "image_api": {
            "provider": "aliyun",
            "api_key": "",
            "endpoint": "",
            "model": "",
        },
        "created_at": "",
        "initialized": False,
    }


# ---- CLI for testing / manual management ----

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "show":
        persona = load_persona()
        print(json.dumps(persona, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "prompt":
        print(get_prompt_prefix())
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        if is_initialized():
            persona = load_persona()
            print(f"Initialized: {persona['name']}")
        else:
            print("Not initialized")
    else:
        print("Usage: persona_manager.py [show|prompt|status]")
