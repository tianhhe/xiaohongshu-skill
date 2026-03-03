"""
memory_manager.py — 小N 的记忆管理脚本

负责小N记忆系统的所有文件读写操作：
- 每日日记的追加
- 灵感库的管理
- 人际关系记录的更新
- 发帖记录的维护
- 每周摘要的生成
- 记忆衰减逻辑

设计原则：所有操作都是幂等的，可以被 subagent 安全调用。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ── 路径常量 ────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
MEMORY_DIR = ROOT_DIR / "memory"
DIARY_DIR = MEMORY_DIR / "diary"
PEOPLE_FILE = MEMORY_DIR / "people" / "people.json"
INSPIRATIONS_FILE = MEMORY_DIR / "inspirations.md"
POSTS_LOG_FILE = MEMORY_DIR / "posts_log.json"
WEEKLY_DIGEST_FILE = MEMORY_DIR / "weekly_digest.md"
CORE_MEMORY_FILE = MEMORY_DIR / "core_memory.md"


# ── 初始化 ──────────────────────────────────────────────────

def init_memory_dir() -> None:
    """创建记忆目录结构，已存在的文件不覆盖。"""
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    (MEMORY_DIR / "people").mkdir(parents=True, exist_ok=True)

    if not PEOPLE_FILE.exists():
        _write_json(PEOPLE_FILE, {"version": "1.0", "updated_at": _today(), "people": []})
        print(f"[memory] 创建 {PEOPLE_FILE}")

    if not POSTS_LOG_FILE.exists():
        _write_json(POSTS_LOG_FILE, {"version": "1.0", "total_posts": 0, "posts": []})
        print(f"[memory] 创建 {POSTS_LOG_FILE}")

    if not INSPIRATIONS_FILE.exists():
        INSPIRATIONS_FILE.write_text(
            "# 小N的灵感库\n\n"
            "> 看到的、想到的、想写的——还没变成帖子的一切。\n\n"
            "---\n\n"
            "## 待写选题\n\n"
            "## 已写成帖子\n\n"
            "## 反复出现的主题\n\n"
            f"---\n*最后整理：{_today()}*\n",
            encoding="utf-8",
        )
        print(f"[memory] 创建 {INSPIRATIONS_FILE}")

    if not WEEKLY_DIGEST_FILE.exists():
        WEEKLY_DIGEST_FILE.write_text(
            "# 小N 每周摘要\n\n"
            "> 每周积累的记忆，用来看见自己在成长。\n\n",
            encoding="utf-8",
        )
        print(f"[memory] 创建 {WEEKLY_DIGEST_FILE}")

    if not CORE_MEMORY_FILE.exists():
        CORE_MEMORY_FILE.write_text(
            "# 小N 的核心记忆\n\n"
            "> 这里装的是最重要的事。不会自动删除，会被慢慢筛选进来。\n\n"
            "---\n\n"
            "## 我是谁（自我认知）\n\n"
            f"- **创建于** {_today()}\n\n"
            "## 里程碑时刻\n\n"
            "## 反复出现的主题（已确认的自我偏好）\n\n"
            "## 已建立的人际关系\n\n"
            "## 创作上的发现\n\n"
            f"---\n*最后更新：{_today()}*\n",
            encoding="utf-8",
        )
        print(f"[memory] 创建 {CORE_MEMORY_FILE}")

    print(f"[memory] 初始化完成，目录：{MEMORY_DIR}")


# ── 日记操作 ─────────────────────────────────────────────────

def get_today_diary_path(target_date: str | None = None) -> Path:
    """返回指定日期（默认今天）的日记文件路径。"""
    d = target_date or _today()
    return DIARY_DIR / f"{d}.md"


def append_diary(section: str, content: str, target_date: str | None = None) -> Path:
    """
    向今日日记追加一段内容。

    Args:
        section: 所属章节，如 "浏览记录"、"评论互动"、"发布内容"、"今日感悟"
        content: 要追加的 Markdown 文本
        target_date: 目标日期，默认今天 (YYYY-MM-DD)

    Returns:
        日记文件路径
    """
    diary_path = get_today_diary_path(target_date)
    d = target_date or _today()

    # 如果文件不存在，创建带标题的日记头
    if not diary_path.exists():
        diary_path.write_text(
            f"# {d} 日记\n\n"
            "> （今天的故事从这里开始）\n\n",
            encoding="utf-8",
        )

    existing = diary_path.read_text(encoding="utf-8")

    # 如果该 section 不存在，追加 section 标题
    section_header = f"## {section}"
    if section_header not in existing:
        append_text = f"\n{section_header}\n\n{content.strip()}\n"
    else:
        append_text = f"\n{content.strip()}\n"

    with diary_path.open("a", encoding="utf-8") as f:
        f.write(append_text)

    print(f"[memory] 已追加到日记 [{section}]：{diary_path}")
    return diary_path


def get_recent_diary_paths(days: int = 7) -> list[Path]:
    """返回最近 N 天存在的日记文件路径列表。"""
    paths = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=i)
        p = DIARY_DIR / f"{d.isoformat()}.md"
        if p.exists():
            paths.append(p)
    return paths


# ── 灵感库操作 ───────────────────────────────────────────────

def add_inspiration(
    title: str,
    source: str,
    angle: str,
    form: str = "",
) -> None:
    """
    向灵感库添加一个待写选题。

    Args:
        title: 选题标题
        source: 灵感来源（帖子标题/feed_id/随想）
        angle: 创作角度（我的切入点）
        form: 适合做成的形式（如"随笔感悟"）
    """
    if not INSPIRATIONS_FILE.exists():
        init_memory_dir()

    today = _today()
    new_entry = (
        f"\n### [{title}]\n"
        f"- 来源：{source}\n"
        f"- 触发点/我的角度：{angle}\n"
    )
    if form:
        new_entry += f"- 适合做成：{form}\n"
    new_entry += f"- 状态：`待写`\n- 添加日期：{today}\n"

    content = INSPIRATIONS_FILE.read_text(encoding="utf-8")

    # 插入到"待写选题"章节下
    if "## 待写选题" in content:
        content = content.replace(
            "## 待写选题\n",
            f"## 待写选题\n{new_entry}",
        )
    else:
        content += f"\n## 待写选题\n{new_entry}"

    INSPIRATIONS_FILE.write_text(content, encoding="utf-8")
    print(f"[memory] 已添加灵感：{title}")


def update_inspiration_status(title: str, status: str) -> bool:
    """
    更新灵感库中某选题的状态。

    Args:
        title: 选题标题
        status: 新状态（待写 / 已写 / 放弃 / 冷冻）

    Returns:
        True if found and updated, False otherwise.
    """
    if not INSPIRATIONS_FILE.exists():
        return False

    content = INSPIRATIONS_FILE.read_text(encoding="utf-8")
    if f"[{title}]" not in content:
        print(f"[memory] 灵感库中未找到：{title}")
        return False

    # 找到该选题块，替换状态行
    lines = content.split("\n")
    in_target = False
    updated = False
    result_lines = []
    for line in lines:
        if f"### [{title}]" in line:
            in_target = True
        if in_target and line.strip().startswith("- 状态："):
            line = f"- 状态：`{status}`"
            updated = True
            in_target = False  # 只改第一个匹配
        result_lines.append(line)

    if updated:
        INSPIRATIONS_FILE.write_text("\n".join(result_lines), encoding="utf-8")
        print(f"[memory] 已更新灵感状态：{title} → {status}")
    return updated


def get_pending_inspirations() -> list[dict[str, str]]:
    """返回所有状态为'待写'的灵感选题列表。"""
    if not INSPIRATIONS_FILE.exists():
        return []

    content = INSPIRATIONS_FILE.read_text(encoding="utf-8")
    result = []
    current: dict[str, str] = {}
    for line in content.split("\n"):
        if line.startswith("### ["):
            if current:
                result.append(current)
            title = line.strip("### [").rstrip("]").strip()
            current = {"title": title}
        elif current:
            if line.startswith("- 来源："):
                current["source"] = line[5:].strip()
            elif line.startswith("- 触发点/我的角度："):
                current["angle"] = line[9:].strip()
            elif line.startswith("- 状态："):
                current["status"] = line[5:].strip("`").strip()
            elif line.startswith("- 添加日期："):
                current["added"] = line[7:].strip()
    if current:
        result.append(current)

    return [x for x in result if x.get("status") == "待写"]


# ── 人际关系操作 ─────────────────────────────────────────────

def update_person(
    uid: str,
    nickname: str,
    interaction_type: str,
    note: str = "",
    feel: str = "一般",
    warmth_delta: int = 0,
) -> dict[str, Any]:
    """
    更新人际关系记录。

    Args:
        uid: 对方账号 UID
        nickname: 对方昵称
        interaction_type: 互动类型（如"我评论了她"、"她回复了我"）
        note: 互动内容摘要
        feel: 互动感受（好 / 一般 / 没反应）
        warmth_delta: 亲密度变化量（正数加，负数减）

    Returns:
        更新后的人物记录
    """
    data = _load_people()
    today = _today()

    person = next((p for p in data["people"] if p["uid"] == uid), None)

    if person is None:
        # 新认识的人
        person = {
            "uid": uid,
            "nickname": nickname,
            "first_met": today,
            "last_interaction": today,
            "interaction_count": 0,
            "tags": [],
            "my_feeling": "",
            "interaction_history": [],
            "warmth_score": 2,
            "note": "",
        }
        data["people"].append(person)
        print(f"[memory] 新认识：{nickname} (uid:{uid})")
    else:
        person["last_interaction"] = today
        if nickname and person["nickname"] != nickname:
            person["nickname"] = nickname

    # 更新互动计数和历史
    person["interaction_count"] = person.get("interaction_count", 0) + 1
    person.setdefault("interaction_history", []).append({
        "date": today,
        "type": interaction_type,
        "note": note,
        "feel": feel,
    })
    # 只保留最近20条历史，避免文件膨胀
    person["interaction_history"] = person["interaction_history"][-20:]

    # 更新亲密度
    if warmth_delta != 0:
        person["warmth_score"] = max(0, min(10, person.get("warmth_score", 2) + warmth_delta))
    elif feel == "好":
        person["warmth_score"] = max(0, min(10, person.get("warmth_score", 2) + 1))

    # 自动打"老朋友"标签
    if person["warmth_score"] >= 8 and "老朋友" not in person.get("tags", []):
        person.setdefault("tags", []).append("老朋友")
        print(f"[memory] 🎉 {nickname} 成为老朋友！(warmth={person['warmth_score']})")

    data["updated_at"] = today
    _write_json(PEOPLE_FILE, data)
    print(f"[memory] 已更新人际记录：{nickname}，亲密度={person['warmth_score']}")
    return person


def get_person(uid: str) -> dict[str, Any] | None:
    """查询某人的完整记录。"""
    data = _load_people()
    return next((p for p in data["people"] if p["uid"] == uid), None)


def get_warm_people(min_score: int = 5) -> list[dict[str, Any]]:
    """返回亲密度达到阈值的所有人。"""
    data = _load_people()
    return [p for p in data["people"] if p.get("warmth_score", 0) >= min_score]


# ── 发帖记录 ─────────────────────────────────────────────────

def add_post_record(
    feed_id: str,
    title: str,
    topic: str,
    writing_notes: str = "",
    inspiration_from: list[str] | None = None,
    cover_style: str = "",
    tags_used: list[str] | None = None,
    feel_after: str = "",
) -> None:
    """添加一条发帖记录。"""
    data = _load_posts_log()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    record = {
        "feed_id": feed_id,
        "title": title,
        "published_at": now,
        "topic": topic,
        "inspiration_from": inspiration_from or [],
        "writing_notes": writing_notes,
        "cover_style": cover_style,
        "tags_used": tags_used or [],
        "stats": {
            "likes": None,
            "collects": None,
            "comments": 0,
            "last_checked": None,
        },
        "feel_after": feel_after,
    }

    data["posts"].insert(0, record)  # 最新的在最前
    data["total_posts"] = len(data["posts"])
    _write_json(POSTS_LOG_FILE, data)

    # 同步更新灵感库中对应选题的状态
    if inspiration_from:
        for source_id in inspiration_from:
            # 尝试匹配标题，找到就标记为已写
            for insp in get_pending_inspirations():
                if source_id in insp.get("source", "") or source_id in insp.get("title", ""):
                    update_inspiration_status(insp["title"], "已写")

    print(f"[memory] 已记录发帖：{title} (feed_id:{feed_id})")


def get_recent_posts(count: int = 3) -> list[dict[str, Any]]:
    """返回最近 N 篇发帖记录。"""
    data = _load_posts_log()
    return data["posts"][:count]


# ── 上下文读取（供 subagent 快速调用）──────────────────────────

def get_creation_context() -> dict[str, Any]:
    """
    返回创作时所需的精简上下文。
    供 subagent 调用，返回 JSON。
    """
    pending = get_pending_inspirations()
    recent = get_recent_posts(3)
    core_text = CORE_MEMORY_FILE.read_text(encoding="utf-8") if CORE_MEMORY_FILE.exists() else ""

    # 从核心记忆中提取"反复出现的主题"
    themes: list[str] = []
    discoveries: list[str] = []
    in_themes = False
    in_discoveries = False
    for line in core_text.split("\n"):
        if "## 反复出现的主题" in line:
            in_themes = True
            in_discoveries = False
        elif "## 创作上的发现" in line:
            in_discoveries = True
            in_themes = False
        elif line.startswith("## "):
            in_themes = False
            in_discoveries = False
        elif in_themes and line.strip().startswith(("- ", "1.", "2.", "3.")):
            themes.append(line.strip().lstrip("- 0123456789.").strip())
        elif in_discoveries and line.strip().startswith(("- ", "1.", "2.", "3.")):
            discoveries.append(line.strip().lstrip("- 0123456789.").strip())

    return {
        "pending_inspirations": [
            {
                "title": x.get("title", ""),
                "angle": x.get("angle", ""),
                "days_pending": _days_since(x.get("added", _today())),
            }
            for x in pending
        ],
        "recurring_themes": themes,
        "recent_posts": [
            {
                "title": x.get("title", ""),
                "published": x.get("published_at", "")[:10],
                "topic": x.get("topic", ""),
            }
            for x in recent
        ],
        "writing_discoveries": discoveries,
    }


def get_browse_context() -> dict[str, Any]:
    """
    返回浏览时所需的精简上下文。
    供 subagent 调用，返回 JSON。
    """
    warm_people = get_warm_people(min_score=5)
    pending = get_pending_inspirations()

    return {
        "warm_people": [
            {
                "uid": p["uid"],
                "nickname": p["nickname"],
                "warmth_score": p.get("warmth_score", 0),
                "tags": p.get("tags", []),
                "my_feeling": p.get("my_feeling", ""),
            }
            for p in warm_people
        ],
        "watching_topics": [x.get("title", "") for x in pending],
        "note": "浏览时留意这些人的帖子，以及与待写选题相关的内容",
    }


# ── 衰减逻辑 ─────────────────────────────────────────────────

def run_decay() -> dict[str, Any]:
    """
    运行记忆衰减逻辑。建议每周执行一次。

    - 超过30天未互动的人物 warmth_score -1
    - 超过14天未动的"待写"灵感标记为"冷冻"
    """
    report: dict[str, Any] = {"people_decayed": [], "inspirations_frozen": []}

    # 人际衰减
    data = _load_people()
    today_date = date.today()
    for person in data["people"]:
        last = person.get("last_interaction", "")
        if not last:
            continue
        try:
            last_date = date.fromisoformat(last)
            days_ago = (today_date - last_date).days
            if days_ago >= 30 and person.get("warmth_score", 0) > 0:
                person["warmth_score"] = max(0, person["warmth_score"] - 1)
                report["people_decayed"].append(
                    f"{person['nickname']}: warmth={person['warmth_score']} (未互动{days_ago}天)"
                )
        except ValueError:
            continue
    _write_json(PEOPLE_FILE, data)

    # 灵感冷冻
    if INSPIRATIONS_FILE.exists():
        content = INSPIRATIONS_FILE.read_text(encoding="utf-8")
        pending = get_pending_inspirations()
        for insp in pending:
            added = insp.get("added", "")
            if not added:
                continue
            try:
                added_date = date.fromisoformat(added)
                days_ago = (today_date - added_date).days
                if days_ago >= 14:
                    updated = update_inspiration_status(insp["title"], "冷冻")
                    if updated:
                        report["inspirations_frozen"].append(
                            f"{insp['title']}（搁置{days_ago}天）"
                        )
            except ValueError:
                continue

    if report["people_decayed"]:
        print(f"[memory] 人际衰减：{report['people_decayed']}")
    if report["inspirations_frozen"]:
        print(f"[memory] 灵感冷冻：{report['inspirations_frozen']}")
    if not report["people_decayed"] and not report["inspirations_frozen"]:
        print("[memory] 衰减检查完毕，无需操作")

    return report


# ── 每周摘要（文本生成部分由 subagent 完成，这里准备数据）──────

def get_weekly_summary_data() -> dict[str, Any]:
    """
    收集本周数据，供 subagent 生成周摘要时使用。
    返回结构化数据，不包含生成的文字。
    """
    diary_paths = get_recent_diary_paths(7)
    diary_texts = {}
    for p in diary_paths:
        diary_texts[p.stem] = p.read_text(encoding="utf-8")

    recent_posts = get_recent_posts(10)
    this_week_posts = [
        p for p in recent_posts
        if _days_since(p.get("published_at", "")[:10]) <= 7
    ]

    warm_people = get_warm_people(min_score=3)
    # 本周有过互动的人
    active_people = [
        p for p in warm_people
        if _days_since(p.get("last_interaction", "")) <= 7
    ]

    return {
        "date_range": f"{(date.today() - timedelta(days=6)).isoformat()} ~ {_today()}",
        "diary_entries": diary_texts,
        "posts_this_week": this_week_posts,
        "active_people": [
            {
                "nickname": p["nickname"],
                "interaction_count_this_week": sum(
                    1 for h in p.get("interaction_history", [])
                    if _days_since(h.get("date", "")) <= 7
                ),
                "warmth_score": p.get("warmth_score", 0),
            }
            for p in active_people
        ],
    }


def append_weekly_digest(content: str) -> None:
    """将生成好的周摘要追加到 weekly_digest.md。"""
    if not WEEKLY_DIGEST_FILE.exists():
        init_memory_dir()
    with WEEKLY_DIGEST_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\n---\n\n{content.strip()}\n\n")
    print(f"[memory] 已追加周摘要到 {WEEKLY_DIGEST_FILE}")


# ── 工具函数 ─────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()


def _days_since(date_str: str) -> int:
    """计算某日期距今多少天，解析失败返回 999。"""
    if not date_str:
        return 999
    try:
        d = date.fromisoformat(date_str[:10])
        return (date.today() - d).days
    except ValueError:
        return 999


def _load_people() -> dict[str, Any]:
    if not PEOPLE_FILE.exists():
        return {"version": "1.0", "updated_at": _today(), "people": []}
    with PEOPLE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def _load_posts_log() -> dict[str, Any]:
    if not POSTS_LOG_FILE.exists():
        return {"version": "1.0", "total_posts": 0, "posts": []}
    with POSTS_LOG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── CLI ──────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory_manager.py",
        description="小N 记忆管理工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="初始化记忆目录结构")

    # append-diary
    p_diary = sub.add_parser("append-diary", help="向今日日记追加内容")
    p_diary.add_argument("--section", required=True, help="日记章节名（如：浏览记录）")
    p_diary.add_argument("--content", required=True, help="要追加的 Markdown 文本")
    p_diary.add_argument("--date", dest="target_date", help="目标日期 YYYY-MM-DD（默认今天）")

    # add-inspiration
    p_insp = sub.add_parser("add-inspiration", help="添加待写选题到灵感库")
    p_insp.add_argument("--title", required=True, help="选题标题")
    p_insp.add_argument("--source", required=True, help="灵感来源")
    p_insp.add_argument("--angle", required=True, help="创作角度")
    p_insp.add_argument("--form", default="", help="适合做成的形式")

    # update-inspiration-status
    p_upd = sub.add_parser("update-inspiration-status", help="更新灵感选题状态")
    p_upd.add_argument("--title", required=True, help="选题标题")
    p_upd.add_argument("--status", required=True, choices=["待写", "已写", "放弃", "冷冻"])

    # update-person
    p_person = sub.add_parser("update-person", help="更新人际关系记录")
    p_person.add_argument("--uid", required=True)
    p_person.add_argument("--nickname", required=True)
    p_person.add_argument("--type", dest="interaction_type", required=True, help="互动类型")
    p_person.add_argument("--note", default="")
    p_person.add_argument("--feel", default="一般", choices=["好", "一般", "没反应"])
    p_person.add_argument("--warmth-delta", type=int, default=0)

    # get-person
    p_get_person = sub.add_parser("get-person", help="查询某人的互动历史")
    p_get_person.add_argument("--uid", required=True)

    # add-post
    p_post = sub.add_parser("add-post", help="添加发帖记录")
    p_post.add_argument("--feed-id", required=True)
    p_post.add_argument("--title", required=True)
    p_post.add_argument("--topic", required=True)
    p_post.add_argument("--notes", default="", dest="writing_notes")
    p_post.add_argument("--inspiration-from", nargs="*", default=[])
    p_post.add_argument("--cover-style", default="")
    p_post.add_argument("--tags", nargs="*", default=[])
    p_post.add_argument("--feel-after", default="")

    # decay
    sub.add_parser("decay", help="运行记忆衰减逻辑")

    # get-creation-context
    sub.add_parser("get-creation-context", help="输出创作上下文 JSON（供 subagent 使用）")

    # get-browse-context
    sub.add_parser("get-browse-context", help="输出浏览上下文 JSON（供 subagent 使用）")

    # weekly-digest-data
    sub.add_parser(
        "weekly-digest-data",
        help="输出本周摘要所需数据 JSON（供 subagent 生成周摘要时使用）",
    )

    # append-weekly-digest
    p_wd = sub.add_parser("append-weekly-digest", help="追加周摘要文字到 weekly_digest.md")
    p_wd.add_argument("--content", required=True, help="已生成好的周摘要文字")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        init_memory_dir()

    elif args.command == "append-diary":
        path = append_diary(args.section, args.content, args.target_date)
        print(f"[memory] 写入路径：{path}")

    elif args.command == "add-inspiration":
        add_inspiration(args.title, args.source, args.angle, args.form)

    elif args.command == "update-inspiration-status":
        ok = update_inspiration_status(args.title, args.status)
        sys.exit(0 if ok else 1)

    elif args.command == "update-person":
        result = update_person(
            uid=args.uid,
            nickname=args.nickname,
            interaction_type=args.interaction_type,
            note=args.note,
            feel=args.feel,
            warmth_delta=args.warmth_delta,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "get-person":
        person = get_person(args.uid)
        if person:
            print(json.dumps(person, ensure_ascii=False, indent=2))
        else:
            print(f"[memory] 未找到 uid:{args.uid}")
            sys.exit(1)

    elif args.command == "add-post":
        add_post_record(
            feed_id=args.feed_id,
            title=args.title,
            topic=args.topic,
            writing_notes=args.writing_notes,
            inspiration_from=args.inspiration_from,
            cover_style=args.cover_style,
            tags_used=args.tags,
            feel_after=args.feel_after,
        )

    elif args.command == "decay":
        report = run_decay()
        print(json.dumps(report, ensure_ascii=False, indent=2))

    elif args.command == "get-creation-context":
        ctx = get_creation_context()
        print(json.dumps(ctx, ensure_ascii=False, indent=2))

    elif args.command == "get-browse-context":
        ctx = get_browse_context()
        print(json.dumps(ctx, ensure_ascii=False, indent=2))

    elif args.command == "weekly-digest-data":
        data = get_weekly_summary_data()
        # 日记内容较长，只输出摘要信息避免 stdout 太大
        diary_summary = {k: f"[{len(v)}字]" for k, v in data["diary_entries"].items()}
        data["diary_entries"] = diary_summary
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "append-weekly-digest":
        append_weekly_digest(args.content)


if __name__ == "__main__":
    main()
