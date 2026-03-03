"""
Playwright-based Xiaohongshu browser for the digital double agent.

Uses Playwright's bundled Chromium to browse XHS, extract feed content,
like/collect notes, and take screenshots. Designed as an alternative
to CDP-based browsing when Chrome setup is problematic.

Usage:
    python pw_browse.py browse-home [--duration 10] [--screenshot /path/to/shot.png]
    python pw_browse.py check-login
    python pw_browse.py login
    python pw_browse.py screenshot [--output /path/to/shot.png]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import random
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
TMP_DIR = os.path.join(PROJECT_DIR, "tmp")
SCREENSHOT_DIR = os.path.join(TMP_DIR, "screenshots")
USER_DATA_DIR = os.path.join(PROJECT_DIR, "playwright_data")

XHS_HOME = "https://www.xiaohongshu.com/explore"
XHS_FOLLOWING = "https://www.xiaohongshu.com/explore?channel_id=homefeed.following_v3"


def _ensure_dirs():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(USER_DATA_DIR, exist_ok=True)


def _sleep(base: float = 1.0, jitter: float = 0.5):
    time.sleep(base + random.uniform(0, jitter))


def _launch_browser(headless: bool = False):
    """Launch persistent Chromium context with Playwright."""
    from playwright.sync_api import sync_playwright
    _ensure_dirs()
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def take_screenshot(page, output: str | None = None) -> str:
    _ensure_dirs()
    if not output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join(SCREENSHOT_DIR, f"screenshot_{ts}.png")
    page.screenshot(path=output, full_page=False)
    print(f"[pw_browse] Screenshot saved: {output}")
    return output


def check_login(page, context=None) -> dict:
    """Check if user is logged in on XHS."""
    page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
    _sleep(3, 1)

    logged_in = False
    try:
        # Method 1: Check cookies
        if context:
            cookies = context.cookies()
            xhs_cookies = [c for c in cookies if 'xiaohongshu' in c.get('domain', '')]
            if len(xhs_cookies) >= 5:
                logged_in = True

        # Method 2: Check for login modal (negative signal)
        has_login_modal = page.query_selector('[class*="login-modal"], [class*="LoginModal"]')
        if has_login_modal:
            logged_in = False

        # Method 3: Check for feed content (positive signal)
        if not logged_in:
            has_feed = page.query_selector('[class*="feed"], .note-item, section.note-item, [class*="note-item"]')
            if has_feed and not has_login_modal:
                logged_in = True
    except Exception:
        pass

    return {"logged_in": logged_in}


def extract_feeds_from_page(page) -> list[dict]:
    """Extract feed items from the current XHS page."""
    feeds = []
    try:
        # Try __INITIAL_STATE__ first
        initial_state = page.evaluate("""
            () => {
                try {
                    const state = window.__INITIAL_STATE__;
                    if (!state) return null;
                    // Try different paths
                    const feedPaths = [
                        state.home?.feeds,
                        state.homeFeed?.feeds,
                        state.explore?.feeds,
                    ];
                    for (const f of feedPaths) {
                        if (f && f.length > 0) return f;
                    }
                    return null;
                } catch(e) { return null; }
            }
        """)
        if initial_state:
            for item in initial_state:
                note = item.get("note_card") or item.get("noteCard") or item
                note_id = item.get("id") or note.get("note_id") or note.get("noteId", "")
                xsec_token = item.get("xsec_token") or item.get("xsecToken", "")
                title = note.get("display_title") or note.get("displayTitle") or note.get("title", "")
                user_info = note.get("user") or {}
                feeds.append({
                    "note_id": note_id,
                    "title": title,
                    "author": user_info.get("nickname") or user_info.get("nick_name", ""),
                    "likes": note.get("liked_count") or note.get("likedCount", ""),
                    "xsec_token": xsec_token,
                    "type": note.get("type", ""),
                })
            if feeds:
                return feeds

        # DOM fallback
        items = page.query_selector_all('section.note-item, a[href*="/explore/"]')
        for item in items[:30]:
            href = item.get_attribute("href") or ""
            title_el = item.query_selector('.title, [class*="title"], .note-title')
            author_el = item.query_selector('.author, [class*="author"], .name')
            title = title_el.inner_text() if title_el else ""
            author = author_el.inner_text() if author_el else ""
            note_id = ""
            if "/explore/" in href:
                note_id = href.split("/explore/")[-1].split("?")[0]
            if note_id:
                feeds.append({
                    "note_id": note_id,
                    "title": title.strip(),
                    "author": author.strip(),
                    "likes": "",
                    "xsec_token": "",
                    "type": "",
                })
    except Exception as e:
        print(f"[pw_browse] Feed extraction error: {e}")
    return feeds


def read_note_detail(page, note_id: str, xsec_token: str = "") -> dict:
    """Navigate to a note and extract its details."""
    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        url += f"?xsec_token={xsec_token}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _sleep(3, 1)

    detail = {"note_id": note_id, "title": "", "content": "", "author": "",
              "likes": "", "collects": "", "comments_count": "", "tags": []}
    try:
        state = page.evaluate("""
            () => {
                try {
                    const s = window.__INITIAL_STATE__;
                    if (!s) return null;
                    const note = s.noteData?.data?.noteData || s.note?.noteDetailMap;
                    if (note && typeof note === 'object') {
                        // noteDetailMap is a dict keyed by note_id
                        const keys = Object.keys(note);
                        if (keys.length > 0) {
                            const n = note[keys[0]]?.note || note[keys[0]];
                            return {
                                title: n.title || '',
                                content: n.desc || '',
                                author: n.user?.nickname || n.user?.nick_name || '',
                                likes: n.interactInfo?.likedCount || '',
                                collects: n.interactInfo?.collectedCount || '',
                                comments_count: n.interactInfo?.commentCount || '',
                                tags: (n.tagList || []).map(t => t.name || t),
                                type: n.type || '',
                            };
                        }
                    }
                    return null;
                } catch(e) { return null; }
            }
        """)
        if state:
            detail.update(state)
        else:
            # DOM fallback
            title_el = page.query_selector('#detail-title, [class*="title"]')
            content_el = page.query_selector('#detail-desc, [class*="desc"], .note-text')
            if title_el:
                detail["title"] = title_el.inner_text().strip()
            if content_el:
                detail["content"] = content_el.inner_text().strip()[:500]
    except Exception as e:
        print(f"[pw_browse] Detail extraction error: {e}")
    return detail


def like_note(page) -> bool:
    """Like the currently open note."""
    try:
        like_btn = page.query_selector('[class*="like"], .like-wrapper .like-icon, span.like-icon')
        if like_btn:
            like_btn.click()
            _sleep(1, 0.5)
            return True
    except Exception as e:
        print(f"[pw_browse] Like error: {e}")
    return False


def collect_note(page, folder_name: str = "") -> bool:
    """Collect/bookmark the currently open note."""
    try:
        collect_btn = page.query_selector('[class*="collect"], .collect-wrapper .collect-icon, span.collect-icon')
        if collect_btn:
            collect_btn.click()
            _sleep(2, 1)
            # Try to select folder if specified
            if folder_name:
                _select_collection_folder(page, folder_name)
            return True
    except Exception as e:
        print(f"[pw_browse] Collect error: {e}")
    return False


def _select_collection_folder(page, folder_name: str):
    """Try to select or create a collection folder in the popup."""
    try:
        _sleep(1, 0.5)
        # Look for folder popup
        folders = page.query_selector_all('[class*="folder"], [class*="collection"] li, .collect-board-item')
        for f in folders:
            text = f.inner_text().strip()
            if folder_name in text:
                f.click()
                _sleep(1)
                return
        # Try to create new folder
        create_btn = page.query_selector('[class*="create"], .new-board, [class*="add-folder"]')
        if create_btn:
            create_btn.click()
            _sleep(1)
            name_input = page.query_selector('input[type="text"], input[placeholder*="收藏夹"]')
            if name_input:
                name_input.fill(folder_name)
                _sleep(0.5)
                confirm = page.query_selector('button:has-text("确定"), button:has-text("创建")')
                if confirm:
                    confirm.click()
                    _sleep(1)
    except Exception as e:
        print(f"[pw_browse] Folder selection error: {e}")


def scroll_and_load(page, times: int = 3):
    """Scroll down to load more content."""
    for _ in range(times):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        _sleep(1.5, 1)


def autonomous_browse(
    page,
    duration_minutes: int = 10,
    interests: list[str] | None = None,
    collection_folder: str = "",
    auto_like: bool = True,
    auto_collect: bool = True,
    max_detail_reads: int = 8,
) -> dict:
    """Autonomously browse XHS, read interesting notes, like & collect."""

    start_time = time.time()
    end_time = start_time + duration_minutes * 60
    interests = interests or []

    result = {
        "duration_minutes": duration_minutes,
        "notes_viewed": 0,
        "notes_liked": 0,
        "notes_collected": 0,
        "interesting_finds": [],
        "feeds_scanned": 0,
    }

    # Phase 1: Browse home feed
    print("[pw_browse] Phase 1: Browsing home feed...")
    page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
    _sleep(3, 1)
    screenshot_path = take_screenshot(page)

    # Scroll a few times to load content
    scroll_and_load(page, 3)
    feeds = extract_feeds_from_page(page)
    result["feeds_scanned"] += len(feeds)
    print(f"[pw_browse] Found {len(feeds)} feeds on home page")

    # Phase 2: Read interesting notes in detail
    detail_count = 0
    seen_ids = set()
    for feed in feeds:
        if time.time() >= end_time:
            break
        if detail_count >= max_detail_reads:
            break
        note_id = feed.get("note_id", "")
        if not note_id or note_id in seen_ids:
            continue
        seen_ids.add(note_id)

        title = feed.get("title", "")
        # Check if this matches our interests
        is_interesting = False
        if interests:
            title_lower = title.lower()
            for interest in interests:
                if interest.lower() in title_lower:
                    is_interesting = True
                    break
        # Also read some random ones
        if not is_interesting and random.random() > 0.4:
            continue

        print(f"[pw_browse] Reading: {title[:40]}...")
        detail = read_note_detail(page, note_id, feed.get("xsec_token", ""))
        result["notes_viewed"] += 1
        detail_count += 1

        # Like if interesting
        if auto_like and (is_interesting or random.random() > 0.5):
            if like_note(page):
                result["notes_liked"] += 1
                detail["liked"] = True

        # Collect if interesting
        if auto_collect and is_interesting:
            if collect_note(page, collection_folder):
                result["notes_collected"] += 1
                detail["collected"] = True

        result["interesting_finds"].append({
            "note_id": note_id,
            "title": detail.get("title") or title,
            "author": detail.get("author") or feed.get("author", ""),
            "content_preview": (detail.get("content") or "")[:150],
            "likes": detail.get("likes", ""),
            "liked": detail.get("liked", False),
            "collected": detail.get("collected", False),
        })

        # Go back to home
        page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
        _sleep(2, 1)

    # Phase 3: Browse following feed if time remains
    if time.time() < end_time:
        print("[pw_browse] Phase 3: Browsing following feed...")
        page.goto(XHS_FOLLOWING, wait_until="domcontentloaded", timeout=30000)
        _sleep(3, 1)
        scroll_and_load(page, 2)
        following_feeds = extract_feeds_from_page(page)
        result["feeds_scanned"] += len(following_feeds)
        print(f"[pw_browse] Found {len(following_feeds)} feeds from following")

        for feed in following_feeds:
            if time.time() >= end_time:
                break
            if detail_count >= max_detail_reads + 4:
                break
            note_id = feed.get("note_id", "")
            if not note_id or note_id in seen_ids:
                continue
            seen_ids.add(note_id)
            title = feed.get("title", "")

            print(f"[pw_browse] Reading following: {title[:40]}...")
            detail = read_note_detail(page, note_id, feed.get("xsec_token", ""))
            result["notes_viewed"] += 1
            detail_count += 1

            if auto_like:
                if like_note(page):
                    result["notes_liked"] += 1

            result["interesting_finds"].append({
                "note_id": note_id,
                "title": detail.get("title") or title,
                "author": detail.get("author") or feed.get("author", ""),
                "content_preview": (detail.get("content") or "")[:150],
                "likes": detail.get("likes", ""),
                "from_following": True,
            })

            page.goto(XHS_FOLLOWING, wait_until="domcontentloaded", timeout=30000)
            _sleep(2, 1)

    # Final screenshot
    final_screenshot = take_screenshot(page)
    result["screenshots"] = [screenshot_path, final_screenshot]
    result["actual_duration_seconds"] = round(time.time() - start_time)

    return result


def main():
    parser = argparse.ArgumentParser(description="Playwright XHS Browser")
    sub = parser.add_subparsers(dest="command", required=True)

    p_browse = sub.add_parser("browse-home", help="Autonomously browse XHS")
    p_browse.add_argument("--duration", type=int, default=10, help="Duration in minutes")
    p_browse.add_argument("--headless", action="store_true", help="Run headless")

    p_login = sub.add_parser("check-login", help="Check login status")
    p_login.add_argument("--headless", action="store_true")

    p_do_login = sub.add_parser("login", help="Open browser for login")

    p_screenshot = sub.add_parser("screenshot", help="Take a screenshot")
    p_screenshot.add_argument("--output", help="Output path")
    p_screenshot.add_argument("--headless", action="store_true")

    args = parser.parse_args()

    if args.command == "login":
        pw, ctx, page = _launch_browser(headless=False)
        page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
        print("[pw_browse] Browser opened. Please log in manually, then press Enter here.")
        input("Press Enter after logging in...")
        take_screenshot(page)
        ctx.close()
        pw.stop()

    elif args.command == "check-login":
        pw, ctx, page = _launch_browser(headless=getattr(args, "headless", False))
        result = check_login(page)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        ctx.close()
        pw.stop()

    elif args.command == "screenshot":
        pw, ctx, page = _launch_browser(headless=getattr(args, "headless", False))
        page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
        _sleep(3)
        path = take_screenshot(page, getattr(args, "output", None))
        print(json.dumps({"path": path}))
        ctx.close()
        pw.stop()

    elif args.command == "browse-home":
        # Load persona config
        sys.path.insert(0, SCRIPT_DIR)
        from persona_manager import load_persona
        persona = load_persona()
        interests = persona.get("interests", [])
        collection_folder = persona.get("collection_folder", "")
        auto_behaviors = persona.get("auto_behaviors", {})

        pw, ctx, page = _launch_browser(headless=getattr(args, "headless", False))
        try:
            # Check login first
            login_status = check_login(page, context=ctx)
            if not login_status.get("logged_in"):
                print(json.dumps({"error": "Not logged in. Run 'python pw_browse.py login' first."}))
                return

            result = autonomous_browse(
                page,
                duration_minutes=args.duration,
                interests=interests,
                collection_folder=collection_folder,
                auto_like=auto_behaviors.get("like_interesting", True),
                auto_collect=auto_behaviors.get("collect_interesting", True),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            ctx.close()
            pw.stop()


if __name__ == "__main__":
    main()
