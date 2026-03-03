"""
CDP-based Xiaohongshu publisher.

Connects to a Chrome instance via Chrome DevTools Protocol to automate
publishing articles on Xiaohongshu (RED) creator center.

CLI usage:
    # Basic commands
    python cdp_publish.py [--host HOST] [--port PORT] check-login [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] fill --title "标题" --content "正文" --images img1.jpg [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] publish --title "标题" --content "正文" --images img1.jpg [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] click-publish [--headless] [--account NAME] [--reuse-existing-tab]
    python cdp_publish.py [--host HOST] [--port PORT] search-feeds --keyword "关键词" [--sort-by 综合|最新|最多点赞|最多评论|最多收藏]
    python cdp_publish.py [--host HOST] [--port PORT] get-feed-detail --feed-id FEED_ID --xsec-token TOKEN
    python cdp_publish.py [--host HOST] [--port PORT] post-comment-to-feed --feed-id FEED_ID --xsec-token TOKEN --content "评论内容"
    python cdp_publish.py [--host HOST] [--port PORT] get-notification-mentions [--wait-seconds 18]
    python cdp_publish.py [--host HOST] [--port PORT] content-data [--page-num 1] [--page-size 10] [--type 0]

    # Account management
    python cdp_publish.py [--host HOST] [--port PORT] login [--account NAME]           # open browser for QR login
    python cdp_publish.py [--host HOST] [--port PORT] re-login [--account NAME]        # clear cookies and re-login same account
    python cdp_publish.py [--host HOST] [--port PORT] switch-account [--account NAME]  # clear cookies + open login for new account
    python cdp_publish.py [--host HOST] [--port PORT] list-accounts                    # list all configured accounts
    python cdp_publish.py [--host HOST] [--port PORT] add-account NAME [--alias ALIAS] # add a new account
    python cdp_publish.py [--host HOST] [--port PORT] remove-account NAME              # remove an account

Library usage:
    from cdp_publish import XiaohongshuPublisher

    publisher = XiaohongshuPublisher()
    publisher.connect()
    publisher.check_login()
    publisher.publish(
        title="Article title",
        content="Article body text",
        image_paths=["/path/to/img1.jpg", "/path/to/img2.jpg"],
    )
"""

from __future__ import annotations

import json
import os
import random
import time
import sys
import csv
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse
from typing import Any

# Add scripts dir to path so sibling modules can be imported in both
# "python scripts/cdp_publish.py" and "import scripts.cdp_publish" modes.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
import websockets.sync.client as ws_client
from feed_explorer import (
    SEARCH_BASE_URL,
    LOCATION_OPTIONS,
    NOTE_TYPE_OPTIONS,
    PUBLISH_TIME_OPTIONS,
    SEARCH_SCOPE_OPTIONS,
    SORT_BY_OPTIONS,
    FeedExplorer,
    FeedExplorerError,
    SearchFilters,
    make_feed_detail_url,
    make_search_url,
)
from run_lock import SingleInstanceError, single_instance

# ---------------------------------------------------------------------------
# Configuration - centralised selectors and URLs for easy maintenance
# ---------------------------------------------------------------------------

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

# Xiaohongshu URLs
XHS_CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"
XHS_HOME_URL = "https://www.xiaohongshu.com"
XHS_NOTIFICATION_URL = "https://www.xiaohongshu.com/notification"
XHS_CREATOR_LOGIN_CHECK_URL = "https://creator.xiaohongshu.com"
XHS_HOME_LOGIN_MODAL_KEYWORD = "登录后推荐更懂你的笔记"
XHS_CONTENT_DATA_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
XHS_CONTENT_DATA_API_PATH = "/api/galaxy/creator/datacenter/note/analyze/list"
XHS_NOTIFICATION_MENTIONS_API_PATH = "/api/sns/web/v1/you/mentions"
XHS_SEARCH_RECOMMEND_API_PATH = "/api/sns/web/v1/search/recommend"
XHS_EXPLORE_URL = "https://www.xiaohongshu.com/explore"
XHS_FOLLOWING_FEED_URL = "https://www.xiaohongshu.com/explore?channel_id=homefeed.following_v3"
XHS_USER_PROFILE_URL_TEMPLATE = "https://www.xiaohongshu.com/user/profile/{user_id}"
XHS_FEED_INACCESSIBLE_KEYWORDS = (
    "当前笔记暂时无法浏览",
    "该内容因违规已被删除",
    "该笔记已被删除",
    "内容不存在",
    "笔记不存在",
    "已失效",
    "私密笔记",
    "仅作者可见",
    "因用户设置，你无法查看",
    "因违规无法查看",
)

# DOM selectors (update these when Xiaohongshu changes their page structure)
# Last verified: 2026-02
SELECTORS = {
    # "上传图文" tab - must click before uploading images
    "image_text_tab": "div.creator-tab",
    "image_text_tab_text": "上传图文",
    # "上传视频" tab - must click before uploading video
    "video_tab": "div.creator-tab",
    "video_tab_text": "上传视频",
    # Upload area - the file input element for images (visible after clicking tab)
    "upload_input": "input.upload-input",
    "upload_input_alt": 'input[type="file"]',
    # Title input field (visible after image upload)
    "title_input": 'input[placeholder*="填写标题"]',
    "title_input_alt": "input.d-text",
    # Content editor area - TipTap/ProseMirror contenteditable div
    "content_editor": "div.tiptap.ProseMirror",
    "content_editor_alt": 'div.ProseMirror[contenteditable="true"]',
    # Publish button
    "publish_button_text": "发布",
    # Login indicator - URL-based check (redirect to /login if not logged in)
    "login_indicator": '.user-info, .creator-header, [class*="user"]',
}

# Timing
PAGE_LOAD_WAIT = 3  # seconds to wait after navigation
TAB_CLICK_WAIT = 2  # seconds to wait after clicking tab
UPLOAD_WAIT = 6  # seconds to wait after image upload for editor to appear
VIDEO_PROCESS_TIMEOUT = 120  # seconds to wait for video processing
VIDEO_PROCESS_POLL = 3  # seconds between video processing status checks
ACTION_INTERVAL = 1  # seconds between actions
MAX_TIMING_JITTER_RATIO = 0.7
DEFAULT_LOGIN_CACHE_TTL_HOURS = 12.0
LOGIN_CACHE_FILE = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "tmp", "login_status_cache.json")
)


def _normalize_timing_jitter(value: float) -> float:
    """Clamp timing jitter to a safe range."""
    return max(0.0, min(MAX_TIMING_JITTER_RATIO, value))


def _is_local_host(host: str) -> bool:
    """Return True when host points to the local machine."""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _resolve_account_name(account_name: str | None) -> str:
    """Resolve explicit or default account name for cache scoping."""
    if account_name and account_name.strip():
        return account_name.strip()
    try:
        from account_manager import get_default_account
        resolved = get_default_account()
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
    except Exception:
        pass
    return "default"


def _build_search_filters_from_args(args) -> SearchFilters | None:
    """Build search filter object from parsed CLI arguments."""
    filters = SearchFilters(
        sort_by=getattr(args, "sort_by", None),
        note_type=getattr(args, "note_type", None),
        publish_time=getattr(args, "publish_time", None),
        search_scope=getattr(args, "search_scope", None),
        location=getattr(args, "location", None),
    )
    return filters if filters.selected_items() else None


def _format_post_time(post_time_ms: Any) -> str:
    """Format note publish time in Asia/Shanghai timezone."""
    if not isinstance(post_time_ms, (int, float)):
        return "-"
    try:
        dt = datetime.fromtimestamp(post_time_ms / 1000, tz=ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def _format_cover_click_rate(value: Any) -> str:
    """Format cover click rate as percentage text."""
    if not isinstance(value, (int, float)):
        return "-"
    normalized = value * 100 if 0 <= value <= 1 else value
    return f"{normalized:.2f}%"


def _format_view_time_avg(value: Any) -> str:
    """Format average view duration in seconds."""
    if not isinstance(value, (int, float)):
        return "-"
    return f"{int(value)}s"


def _metric_or_dash(note: dict[str, Any], field: str) -> Any:
    """Return field value if present, otherwise '-'."""
    value = note.get(field)
    return "-" if value is None else value


def _map_note_infos_to_content_rows(note_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map note_infos payload to content table rows."""
    rows: list[dict[str, Any]] = []
    for note in note_infos:
        rows.append({
            "标题": note.get("title") or "-",
            "发布时间": _format_post_time(note.get("post_time")),
            "曝光": _metric_or_dash(note, "imp_count"),
            "观看": _metric_or_dash(note, "read_count"),
            "封面点击率": _format_cover_click_rate(note.get("coverClickRate")),
            "点赞": _metric_or_dash(note, "like_count"),
            "评论": _metric_or_dash(note, "comment_count"),
            "收藏": _metric_or_dash(note, "fav_count"),
            "涨粉": _metric_or_dash(note, "increase_fans_count"),
            "分享": _metric_or_dash(note, "share_count"),
            "人均观看时长": _format_view_time_avg(note.get("view_time_avg")),
            "弹幕": _metric_or_dash(note, "danmaku_count"),
            "操作": "详情数据",
            "_id": note.get("id") or "",
        })
    return rows


def _write_content_data_csv(csv_file: str, rows: list[dict[str, Any]]) -> str:
    """Write content rows to a UTF-8 CSV file and return absolute path."""
    abs_path = os.path.abspath(csv_file)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    columns = [
        "标题",
        "发布时间",
        "曝光",
        "观看",
        "封面点击率",
        "点赞",
        "评论",
        "收藏",
        "涨粉",
        "分享",
        "人均观看时长",
        "弹幕",
        "操作",
        "_id",
    ]
    with open(abs_path, "w", encoding="utf-8-sig", newline="") as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return abs_path


class CDPError(Exception):
    """Error communicating with Chrome via CDP."""


class XiaohongshuPublisher:
    """Automates publishing to Xiaohongshu via CDP."""

    def __init__(
        self,
        host: str = CDP_HOST,
        port: int = CDP_PORT,
        timing_jitter: float = 0.25,
        account_name: str | None = None,
    ):
        self.host = host
        self.port = port
        self.ws = None
        self._msg_id = 0
        self.timing_jitter = _normalize_timing_jitter(timing_jitter)
        self.account_name = (account_name or "default").strip() or "default"
        self.login_cache_ttl_hours = DEFAULT_LOGIN_CACHE_TTL_HOURS
        self.login_cache_ttl_seconds = self.login_cache_ttl_hours * 3600
        self.login_cache_file = LOGIN_CACHE_FILE

    def _login_cache_key(self, scope: str) -> str:
        """Build a unique cache key for one login scope."""
        return f"{self.host}:{self.port}:{self.account_name}:{scope}"

    def _load_login_cache(self) -> dict[str, Any]:
        """Load login cache payload from local JSON file."""
        if not os.path.exists(self.login_cache_file):
            return {"entries": {}}

        try:
            with open(self.login_cache_file, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
        except Exception:
            return {"entries": {}}

        if not isinstance(payload, dict):
            return {"entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def _save_login_cache(self, payload: dict[str, Any]):
        """Persist login cache payload to local JSON file."""
        parent = os.path.dirname(self.login_cache_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.login_cache_file, "w", encoding="utf-8") as cache_file:
            json.dump(payload, cache_file, ensure_ascii=False, indent=2)

    def _get_cached_login_status(self, scope: str) -> bool | None:
        """Return cached login status when cache is still fresh."""
        if self.login_cache_ttl_seconds <= 0:
            return None

        payload = self._load_login_cache()
        entries = payload.get("entries", {})
        entry = entries.get(self._login_cache_key(scope))
        if not isinstance(entry, dict):
            return None

        checked_at = entry.get("checked_at")
        logged_in = entry.get("logged_in")
        if not isinstance(checked_at, (int, float)) or not isinstance(logged_in, bool):
            return None

        age_seconds = time.time() - float(checked_at)
        if age_seconds < 0 or age_seconds > self.login_cache_ttl_seconds:
            return None

        if not logged_in:
            return None

        age_minutes = int(age_seconds // 60)
        print(
            "[cdp_publish] Using cached login status "
            f"({scope}, age={age_minutes}m, ttl={self.login_cache_ttl_hours:g}h)."
        )
        return logged_in

    def _set_login_cache(self, scope: str, logged_in: bool):
        """Save positive login status cache for a specific scope."""
        if not logged_in:
            self._clear_login_cache(scope=scope)
            return

        payload = self._load_login_cache()
        entries = payload.setdefault("entries", {})
        entries[self._login_cache_key(scope)] = {
            "logged_in": True,
            "checked_at": int(time.time()),
        }
        self._save_login_cache(payload)

    def _clear_login_cache(self, scope: str | None = None):
        """Clear login cache entries for current host/port/account."""
        payload = self._load_login_cache()
        entries = payload.get("entries", {})
        if not isinstance(entries, dict) or not entries:
            return

        changed = False
        if scope:
            key = self._login_cache_key(scope)
            if key in entries:
                entries.pop(key, None)
                changed = True
        else:
            prefix = self._login_cache_key("")
            for key in list(entries.keys()):
                if key.startswith(prefix):
                    entries.pop(key, None)
                    changed = True

        if changed:
            payload["entries"] = entries
            self._save_login_cache(payload)

    def _sleep(self, base_seconds: float, minimum_seconds: float = 0.05):
        """Sleep with optional randomized jitter to avoid rigid timing patterns."""
        base = max(minimum_seconds, float(base_seconds))
        if self.timing_jitter <= 0:
            time.sleep(base)
            return

        delta = base * self.timing_jitter
        low = max(minimum_seconds, base - delta)
        high = max(low, base + delta)
        time.sleep(random.uniform(low, high))

    # ------------------------------------------------------------------
    # CDP connection management
    # ------------------------------------------------------------------

    def _get_targets(self) -> list[dict]:
        """Get list of available browser targets (tabs). Retries once on failure."""
        url = f"http://{self.host}:{self.port}/json"
        for attempt in range(2):
            try:
                resp = requests.get(url, timeout=5, proxies={"http": None, "https": None})
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == 0:
                    if _is_local_host(self.host):
                        print(f"[cdp_publish] CDP connection failed ({e}), restarting Chrome...")
                        from chrome_launcher import ensure_chrome
                        ensure_chrome(port=self.port)
                    else:
                        print(
                            f"[cdp_publish] CDP connection failed ({e}), retrying remote endpoint "
                            f"{self.host}:{self.port}..."
                        )
                    self._sleep(2, minimum_seconds=1.0)
                else:
                    raise CDPError(f"Cannot reach Chrome on {self.host}:{self.port}: {e}")

    def _find_or_create_tab(
        self,
        target_url_prefix: str = "",
        reuse_existing_tab: bool = False,
    ) -> str:
        """
        Find a tab to connect.

        Default behavior is backward-compatible: create a new tab first.
        When `reuse_existing_tab` is enabled, prefer reusing an existing page tab
        to reduce focus switching in headed mode.
        """
        targets = self._get_targets()
        pages = [
            t for t in targets
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        ]

        if target_url_prefix:
            for t in pages:
                if t.get("url", "").startswith(target_url_prefix):
                    return t["webSocketDebuggerUrl"]

        if reuse_existing_tab and pages:
            url = pages[0].get("url", "")
            print(
                "[cdp_publish] Reusing existing tab to reduce focus switching: "
                f"{url}"
            )
            return pages[0]["webSocketDebuggerUrl"]

        # Create a new tab
        resp = requests.put(
            f"http://{self.host}:{self.port}/json/new?{XHS_CREATOR_URL}",
            timeout=5,
            proxies={"http": None, "https": None},
        )
        if resp.ok:
            ws_url = resp.json().get("webSocketDebuggerUrl", "")
            if ws_url:
                return ws_url

        # Fallback: use first available page
        if pages:
            return pages[0]["webSocketDebuggerUrl"]

        raise CDPError("No browser tabs available.")

    def connect(self, target_url_prefix: str = "", reuse_existing_tab: bool = False):
        """Connect to a Chrome tab via WebSocket."""
        ws_url = self._find_or_create_tab(
            target_url_prefix=target_url_prefix,
            reuse_existing_tab=reuse_existing_tab,
        )
        if not ws_url:
            raise CDPError("Could not obtain WebSocket URL for any tab.")

        print(f"[cdp_publish] Connecting to {ws_url}")
        # Temporarily disable proxy for local WebSocket connections
        # (websockets lib honors HTTP_PROXY and routes local CDP through proxy)
        saved_proxies = {}
        if _is_local_host(self.host):
            for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
                if key in os.environ:
                    saved_proxies[key] = os.environ.pop(key)
        try:
            self.ws = ws_client.connect(ws_url)
        finally:
            os.environ.update(saved_proxies)
        print("[cdp_publish] Connected to Chrome tab.")

    def disconnect(self):
        """Close the WebSocket connection."""
        if self.ws:
            self.ws.close()
            self.ws = None

    # ------------------------------------------------------------------
    # CDP command helpers
    # ------------------------------------------------------------------

    def _send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and return the result."""
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params

        self.ws.send(json.dumps(msg))

        # Wait for the matching response
        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                if "error" in data:
                    raise CDPError(f"CDP error: {data['error']}")
                return data.get("result", {})
            # else: it's an event, skip it

    def _evaluate(self, expression: str) -> Any:
        """Execute JavaScript in the page and return the result value."""
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote_obj = result.get("result", {})
        if remote_obj.get("subtype") == "error":
            raise CDPError(f"JS error: {remote_obj.get('description', remote_obj)}")
        return remote_obj.get("value")

    def _navigate(self, url: str):
        """Navigate the current tab to the given URL and wait for load."""
        print(f"[cdp_publish] Navigating to {url}")
        self._send("Page.enable")
        self._send("Page.navigate", {"url": url})
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.0)

    # ------------------------------------------------------------------
    # Login check
    # ------------------------------------------------------------------

    def check_login(self) -> bool:
        """
        Navigate to Xiaohongshu creator center and check if the user is logged in.

        Returns True if logged in. If not logged in, prints instructions
        and returns False.
        """
        scope = "creator"
        cached_status = self._get_cached_login_status(scope)
        if cached_status is not None:
            if cached_status:
                print("[cdp_publish] Login confirmed (cached).")
            return cached_status

        self._navigate(XHS_CREATOR_LOGIN_CHECK_URL)
        self._sleep(2, minimum_seconds=1.0)

        # Check if we got redirected to a login page
        current_url = self._evaluate("window.location.href")
        print(f"[cdp_publish] Current URL: {current_url}")

        if "login" in current_url.lower():
            self._set_login_cache(scope, logged_in=False)
            print(
                "\n[cdp_publish] NOT LOGGED IN.\n"
                "  Please scan the QR code in the Chrome window to log in,\n"
                "  then run this script again.\n"
            )
            return False

        self._set_login_cache(scope, logged_in=True)
        print("[cdp_publish] Login confirmed.")
        return True

    def _home_login_prompt_visible(self, keyword: str) -> bool:
        """Return True when home page login prompt modal is visible."""
        keyword_literal = json.dumps(keyword)
        visible = self._evaluate(f"""
            (() => {{
                const keyword = {keyword_literal};
                const normalize = (text) => (text || "").replace(/\\s+/g, " ").trim();
                const containsKeyword = (text) => normalize(text).includes(keyword);

                const modalSelectors = [
                    "[class*='login']",
                    "[class*='modal']",
                    "[class*='popup']",
                    "[class*='dialog']",
                    "[class*='mask']",
                ];

                for (const selector of modalSelectors) {{
                    const nodes = document.querySelectorAll(selector);
                    for (const node of nodes) {{
                        if (!(node instanceof HTMLElement)) {{
                            continue;
                        }}
                        if (node.offsetParent === null) {{
                            continue;
                        }}
                        if (containsKeyword(node.textContent) || containsKeyword(node.innerText)) {{
                            return true;
                        }}
                    }}
                }}

                if (document.body && containsKeyword(document.body.innerText)) {{
                    return true;
                }}
                return false;
            }})()
        """)
        return bool(visible)

    def check_home_login(
        self,
        keyword: str = XHS_HOME_LOGIN_MODAL_KEYWORD,
        wait_seconds: float = 8.0,
    ) -> bool:
        """
        Check login state on Xiaohongshu home page.

        Login prompt modal keyword (default: "登录后推荐更懂你的笔记") indicates
        unauthenticated state for the xiaohongshu.com home/feed domain.
        """
        scope = "home"
        cached_status = self._get_cached_login_status(scope)
        if cached_status is not None:
            if cached_status:
                print("[cdp_publish] Home login confirmed (cached).")
            return cached_status

        self._navigate(XHS_HOME_URL)
        self._sleep(2, minimum_seconds=1.0)

        current_url = self._evaluate("window.location.href")
        print(f"[cdp_publish] Home URL: {current_url}")
        if isinstance(current_url, str) and "login" in current_url.lower():
            self._set_login_cache(scope, logged_in=False)
            print(
                "\n[cdp_publish] NOT LOGGED IN (HOME).\n"
                "  Please log in on xiaohongshu.com and run this command again.\n"
            )
            return False

        deadline = time.time() + max(1.0, wait_seconds)
        while time.time() < deadline:
            if self._home_login_prompt_visible(keyword):
                self._set_login_cache(scope, logged_in=False)
                print(
                    "\n[cdp_publish] NOT LOGGED IN (HOME).\n"
                    f"  Detected login prompt keyword: {keyword}\n"
                    "  Please log in on xiaohongshu.com and run this command again.\n"
                )
                return False
            self._sleep(0.7, minimum_seconds=0.2)

        self._set_login_cache(scope, logged_in=True)
        print("[cdp_publish] Home login confirmed.")
        return True

    def clear_cookies(self, domain: str = ".xiaohongshu.com"):
        """
        Clear all cookies for the given domain to force re-login.

        Used when switching accounts.
        """
        print(f"[cdp_publish] Clearing cookies for {domain}...")
        self._send("Network.enable")
        self._send("Network.clearBrowserCookies")
        # Also clear storage
        self._send("Storage.clearDataForOrigin", {
            "origin": "https://www.xiaohongshu.com",
            "storageTypes": "cookies,local_storage,session_storage",
        })
        self._send("Storage.clearDataForOrigin", {
            "origin": "https://creator.xiaohongshu.com",
            "storageTypes": "cookies,local_storage,session_storage",
        })
        self._clear_login_cache()
        print("[cdp_publish] Cookies and storage cleared.")

    def open_login_page(self):
        """
        Navigate to the Xiaohongshu login page for QR code scanning.

        Used for initial login or after clearing cookies for account switch.
        """
        self._navigate(XHS_CREATOR_LOGIN_CHECK_URL)
        self._sleep(2, minimum_seconds=1.0)
        current_url = self._evaluate("window.location.href")
        if "login" not in current_url.lower():
            # Already logged in, navigate to login page explicitly
            self._navigate("https://creator.xiaohongshu.com/login")
            self._sleep(2, minimum_seconds=1.0)
        self._clear_login_cache()
        print(
            "\n[cdp_publish] Login page is open.\n"
            "  Please scan the QR code in the Chrome window to log in.\n"
        )

    # ------------------------------------------------------------------
    # Feed discovery actions
    # ------------------------------------------------------------------

    def _prepare_search_input_keyword(self, keyword: str) -> dict[str, Any]:
        """Focus search input and type keyword without submitting."""
        keyword_literal = json.dumps(keyword, ensure_ascii=False)
        result = self._evaluate(f"""
            (async () => {{
                const keyword = {keyword_literal};
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

                const isVisible = (node) => {{
                    if (!(node instanceof HTMLElement)) {{
                        return false;
                    }}
                    if (node.offsetParent === null) {{
                        return false;
                    }}
                    const rect = node.getBoundingClientRect();
                    return rect.width >= 8 && rect.height >= 8;
                }};

                const selectors = [
                    "#search-input",
                    "input.search-input",
                    "input[type='search']",
                    "input[placeholder*='搜索']",
                    "[class*='search'] input",
                ];

                let inputEl = null;
                for (const selector of selectors) {{
                    const nodes = document.querySelectorAll(selector);
                    for (const node of nodes) {{
                        if (!(node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement)) {{
                            continue;
                        }}
                        if (node.disabled || !isVisible(node)) {{
                            continue;
                        }}
                        inputEl = node;
                        break;
                    }}
                    if (inputEl) {{
                        break;
                    }}
                }}

                if (!inputEl) {{
                    return {{ ok: false, reason: "search_input_not_found" }};
                }}

                const setValue = (value) => {{
                    const proto = inputEl instanceof HTMLTextAreaElement
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
                    if (descriptor && typeof descriptor.set === "function") {{
                        descriptor.set.call(inputEl, value);
                    }} else {{
                        inputEl.value = value;
                    }}
                    inputEl.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    inputEl.dispatchEvent(new Event("change", {{ bubbles: true }}));
                }};

                inputEl.focus();
                await sleep(120);
                setValue("");
                await sleep(80);

                let typed = "";
                for (const ch of Array.from(keyword)) {{
                    typed += ch;
                    setValue(typed);
                    await sleep(55 + Math.floor(Math.random() * 70));
                }}
                await sleep(220);
                return {{ ok: true, reason: "" }};
            }})()
        """)
        if not isinstance(result, dict):
            return {"ok": False, "reason": "unexpected_result"}
        reason = result.get("reason")
        return {
            "ok": bool(result.get("ok")),
            "reason": reason if isinstance(reason, str) else "unknown",
        }

    def _extract_recommend_keywords_from_payload(
        self,
        payload: dict[str, Any],
        keyword: str,
        max_suggestions: int,
    ) -> list[str]:
        """Extract recommendation keywords from search recommend API payload."""
        ignored_texts = {
            "历史记录",
            "猜你想搜",
            "相关搜索",
            "热门搜索",
            "大家都在搜",
            "清空历史",
            "删除历史",
        }

        def normalize_text(value: str) -> str:
            return " ".join(value.split()).strip()

        def push_text(output: list[str], seen: set[str], value: str):
            normalized = normalize_text(value)
            if not normalized or normalized == keyword:
                return
            if normalized in ignored_texts:
                return
            if len(normalized) < 2 or len(normalized) > 36:
                return
            if normalized in seen:
                return
            seen.add(normalized)
            output.append(normalized)

        ordered: list[str] = []
        seen: set[str] = set()
        stack: list[Any] = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, str):
                        key_lc = key.lower()
                        if any(
                            hint in key_lc
                            for hint in (
                                "word",
                                "query",
                                "keyword",
                                "text",
                                "title",
                                "name",
                                "suggest",
                            )
                        ):
                            push_text(ordered, seen, value)
                        continue
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(node, list):
                for item in node:
                    if isinstance(item, str):
                        push_text(ordered, seen, item)
                        continue
                    if isinstance(item, (dict, list)):
                        stack.append(item)

        keyword_prefix = keyword[:2]
        ranked: list[tuple[int, int, str]] = []
        for idx, text in enumerate(ordered):
            score = 0
            if keyword and (keyword in text or text in keyword):
                score += 3
            elif keyword_prefix and keyword_prefix in text:
                score += 1
            ranked.append((score, idx, text))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[: max(1, max_suggestions)]]

    def _capture_search_recommendations_via_network(
        self,
        keyword: str,
        wait_seconds: float = 8.0,
        max_suggestions: int = 12,
    ) -> dict[str, Any]:
        """Capture recommend API response from real page traffic."""
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        self._send("Network.enable", {"maxPostDataSize": 65536})
        self._send("Network.setCacheDisabled", {"cacheDisabled": True})

        typed = self._prepare_search_input_keyword(keyword)
        if not typed.get("ok"):
            reason = typed.get("reason") or "type_keyword_failed"
            return {"ok": False, "reason": str(reason), "suggestions": []}

        deadline = time.time() + max(2.0, float(wait_seconds))
        request_meta_by_id: dict[str, dict[str, str]] = {}
        exact_match: tuple[str, str] | None = None
        fallback_match: tuple[str, str] | None = None

        while time.time() < deadline:
            timeout = min(1.0, max(0.1, deadline - time.time()))
            try:
                raw = self.ws.recv(timeout=timeout)
            except TimeoutError:
                continue

            message = json.loads(raw)
            method = message.get("method")
            params = message.get("params", {})

            if method == "Network.requestWillBeSent":
                request_id = params.get("requestId")
                request = params.get("request", {})
                if isinstance(request_id, str):
                    request_meta_by_id[request_id] = {
                        "url": request.get("url", ""),
                        "method": str(request.get("method", "")).upper(),
                    }
                continue

            if method != "Network.responseReceived":
                continue

            request_id = params.get("requestId")
            if not isinstance(request_id, str):
                continue

            request_meta = request_meta_by_id.get(request_id, {})
            request_url = request_meta.get("url", "")
            if XHS_SEARCH_RECOMMEND_API_PATH not in request_url:
                continue
            if request_meta.get("method") == "OPTIONS":
                continue

            status = int(params.get("response", {}).get("status") or 0)
            if status != 200:
                continue

            fallback_match = (request_id, request_url)
            try:
                query = parse_qs(urlparse(request_url).query)
                request_keyword = (query.get("keyword") or [""])[0].strip()
            except Exception:
                request_keyword = ""

            if request_keyword == keyword:
                exact_match = (request_id, request_url)
                break

        target = exact_match or fallback_match
        if not target:
            return {"ok": False, "reason": "recommend_request_timeout", "suggestions": []}

        request_id, request_url = target
        body_result = self._send("Network.getResponseBody", {"requestId": request_id})
        body_text = body_result.get("body", "")
        if body_result.get("base64Encoded"):
            body_text = base64.b64decode(body_text).decode("utf-8", errors="replace")

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "recommend_invalid_json", "suggestions": []}
        if not isinstance(payload, dict):
            return {"ok": False, "reason": "recommend_invalid_payload", "suggestions": []}

        suggestions = self._extract_recommend_keywords_from_payload(
            payload=payload,
            keyword=keyword,
            max_suggestions=max_suggestions,
        )
        return {
            "ok": True,
            "reason": "",
            "request_url": request_url,
            "suggestions": suggestions,
        }

    def search_feeds(
        self,
        keyword: str,
        filters: SearchFilters | None = None,
    ) -> dict[str, Any]:
        """
        Search Xiaohongshu feeds by keyword and optional filters.

        Returns:
            {
                "keyword": str,
                "recommended_keywords": list[str],  # dropdown related terms
                "feeds": list[dict[str, Any]],      # extracted from __INITIAL_STATE__
            }
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        keyword = keyword.strip()
        if not keyword:
            raise CDPError("Keyword cannot be empty.")

        self._navigate(SEARCH_BASE_URL)
        self._sleep(2, minimum_seconds=1.0)

        explorer = FeedExplorer(
            self._evaluate,
            self._sleep,
            move_mouse=self._move_mouse,
            click_mouse=self._click_mouse,
        )

        recommendation_result = self._capture_search_recommendations_via_network(keyword=keyword)
        recommended_keywords = recommendation_result.get("suggestions", [])

        if not recommendation_result.get("ok"):
            reason = recommendation_result.get("reason") or "recommend_api_failed"
            print(
                "[cdp_publish] Warning: failed to capture search recommendations via API. "
                f"reason={reason}"
            )

        # Always navigate with keyword URL to keep feed extraction stable.
        search_url = make_search_url(keyword)
        self._navigate(search_url)
        self._sleep(2, minimum_seconds=1.0)

        try:
            feeds = explorer.search_feeds(keyword=keyword, filters=filters)
        except FeedExplorerError as e:
            raise CDPError(str(e)) from e

        print(
            f"[cdp_publish] Search completed. keyword={keyword}, "
            f"recommended_keywords={len(recommended_keywords)}, feeds={len(feeds)}"
        )
        return {
            "keyword": keyword,
            "recommended_keywords": recommended_keywords,
            "feeds": feeds,
        }

    def get_feed_detail(self, feed_id: str, xsec_token: str) -> dict[str, Any]:
        """
        Get feed detail from note page initial state.

        Returns a detail object containing `note` and `comments` (if available).
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        feed_id = feed_id.strip()
        xsec_token = xsec_token.strip()
        if not feed_id:
            raise CDPError("feed_id cannot be empty.")
        if not xsec_token:
            raise CDPError("xsec_token cannot be empty.")

        detail_url = make_feed_detail_url(feed_id, xsec_token)
        self._navigate(detail_url)
        self._sleep(2, minimum_seconds=1.0)

        explorer = FeedExplorer(self._evaluate, self._sleep)
        try:
            detail = explorer.get_feed_detail(feed_id=feed_id)
        except FeedExplorerError as e:
            raise CDPError(str(e)) from e

        print(f"[cdp_publish] Feed detail loaded. feed_id={feed_id}")
        return detail

    def _check_feed_page_accessible(self):
        """
        Check whether the currently opened feed detail page is accessible.

        Raises:
            CDPError: If page is inaccessible due to privacy/deletion/violation.
        """
        keyword_list_literal = json.dumps(
            list(XHS_FEED_INACCESSIBLE_KEYWORDS),
            ensure_ascii=False,
        )
        issue = self._evaluate(f"""
            (() => {{
                const wrappers = document.querySelectorAll(
                    ".access-wrapper, .error-wrapper, .not-found-wrapper, .blocked-wrapper"
                );
                if (!wrappers.length) {{
                    return "";
                }}

                let text = "";
                for (const el of wrappers) {{
                    const chunk = (el.innerText || el.textContent || "").trim();
                    if (chunk) {{
                        text += (text ? " " : "") + chunk;
                    }}
                }}
                const fullText = text.trim();
                if (!fullText) {{
                    return "";
                }}

                const keywords = {keyword_list_literal};
                for (const kw of keywords) {{
                    if (fullText.includes(kw)) {{
                        return kw;
                    }}
                }}
                return fullText.slice(0, 180);
            }})()
        """)
        if isinstance(issue, str) and issue.strip():
            raise CDPError(f"Feed page is not accessible: {issue.strip()}")

    def _fill_comment_content(self, content: str) -> int:
        """
        Fill comment content into feed detail page input.

        Returns:
            Filled character length.
        """
        content_literal = json.dumps(content, ensure_ascii=False)
        result = self._evaluate(f"""
            (() => {{
                const commentText = {content_literal};
                const candidates = [
                    "div.input-box div.content-edit p.content-input",
                    "div.input-box div.content-edit [contenteditable='true']",
                    "div.input-box .content-input",
                    "p.content-input",
                    "[class*='content-edit'] [contenteditable='true']",
                ];

                let inputEl = null;
                for (const selector of candidates) {{
                    const node = document.querySelector(selector);
                    if (!(node instanceof HTMLElement)) {{
                        continue;
                    }}
                    if (node.offsetParent === null) {{
                        continue;
                    }}
                    inputEl = node;
                    break;
                }}

                if (!inputEl) {{
                    return {{ ok: false, reason: "comment_input_not_found" }};
                }}

                inputEl.focus();

                if (inputEl instanceof HTMLInputElement || inputEl instanceof HTMLTextAreaElement) {{
                    inputEl.value = commentText;
                    inputEl.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    inputEl.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    return {{
                        ok: true,
                        length: inputEl.value.trim().length,
                    }};
                }}

                const asEditable = inputEl;
                if (!asEditable.isContentEditable && asEditable.tagName.toLowerCase() !== "p") {{
                    const nested = asEditable.querySelector("[contenteditable='true'], p.content-input");
                    if (nested instanceof HTMLElement) {{
                        nested.focus();
                        inputEl = nested;
                    }}
                }}

                if (inputEl.tagName.toLowerCase() === "p") {{
                    inputEl.textContent = commentText;
                }} else {{
                    const lines = commentText.split("\\n");
                    const escapeHtml = (text) => text
                        .replaceAll("&", "&amp;")
                        .replaceAll("<", "&lt;")
                        .replaceAll(">", "&gt;");
                    const html = lines.map((line) => {{
                        if (!line.trim()) {{
                            return "<p><br></p>";
                        }}
                        return "<p>" + escapeHtml(line) + "</p>";
                    }}).join("");
                    inputEl.innerHTML = html || "<p><br></p>";
                }}

                inputEl.dispatchEvent(new Event("input", {{ bubbles: true }}));
                inputEl.dispatchEvent(new Event("change", {{ bubbles: true }}));

                const finalText = (
                    inputEl.innerText ||
                    inputEl.textContent ||
                    ""
                ).trim();
                return {{
                    ok: true,
                    length: finalText.length,
                }};
            }})()
        """)
        if not isinstance(result, dict) or not result.get("ok"):
            reason = "unknown"
            if isinstance(result, dict):
                reason = str(result.get("reason", reason))
            raise CDPError(f"Failed to fill comment content: {reason}")

        return int(result.get("length", 0))

    def post_comment_to_feed(self, feed_id: str, xsec_token: str, content: str) -> dict[str, Any]:
        """
        Post a top-level comment to a feed detail page.
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        feed_id = feed_id.strip()
        xsec_token = xsec_token.strip()
        content = content.strip()

        if not feed_id:
            raise CDPError("feed_id cannot be empty.")
        if not xsec_token:
            raise CDPError("xsec_token cannot be empty.")
        if not content:
            raise CDPError("content cannot be empty.")

        detail_url = make_feed_detail_url(feed_id, xsec_token)
        self._navigate(detail_url)
        self._sleep(2, minimum_seconds=1.0)
        self._check_feed_page_accessible()

        input_rect_js = """
            (function() {
                const selectors = [
                    "div.input-box div.content-edit span",
                    "div.input-box div.content-edit p.content-input",
                    "div.input-box div.content-edit",
                    "div.input-box",
                ];
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (!(el instanceof HTMLElement) || el.offsetParent === null) {
                        continue;
                    }
                    const r = el.getBoundingClientRect();
                    if (r.width < 8 || r.height < 8) {
                        continue;
                    }
                    return { x: r.x, y: r.y, width: r.width, height: r.height };
                }
                return null;
            })();
        """
        try:
            self._click_element_by_cdp("comment input box", input_rect_js)
            self._sleep(0.4, minimum_seconds=0.15)
        except CDPError:
            print(
                "[cdp_publish] Warning: Could not click comment input via CDP. "
                "Falling back to direct focus."
            )

        filled_len = self._fill_comment_content(content)
        self._sleep(0.6, minimum_seconds=0.2)

        submit_rect_js = """
            (function() {
                const selectors = [
                    "div.bottom button.submit",
                    "div.bottom button[class*='submit']",
                    "button.submit",
                    "button[class*='submit']",
                    "button[type='submit']",
                ];
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (!(el instanceof HTMLButtonElement) || el.offsetParent === null) {
                        continue;
                    }
                    if (el.disabled) {
                        continue;
                    }
                    const r = el.getBoundingClientRect();
                    if (r.width < 8 || r.height < 8) {
                        continue;
                    }
                    return { x: r.x, y: r.y, width: r.width, height: r.height };
                }
                const fallbackTexts = new Set(["发送", "提交", "评论"]);
                const buttons = document.querySelectorAll("button");
                for (const button of buttons) {
                    if (!(button instanceof HTMLButtonElement) || button.offsetParent === null) {
                        continue;
                    }
                    if (button.disabled) {
                        continue;
                    }
                    const text = (button.textContent || "").replace(/\\s+/g, " ").trim();
                    if (!fallbackTexts.has(text)) {
                        continue;
                    }
                    const r = button.getBoundingClientRect();
                    if (r.width < 8 || r.height < 8) {
                        continue;
                    }
                    return { x: r.x, y: r.y, width: r.width, height: r.height };
                }
                return null;
            })();
        """
        self._click_element_by_cdp("comment submit button", submit_rect_js)
        self._sleep(1.0, minimum_seconds=0.4)

        print(f"[cdp_publish] Comment posted. feed_id={feed_id}, length={filled_len}")
        return {
            "feed_id": feed_id,
            "xsec_token": xsec_token,
            "content_length": filled_len,
            "success": True,
        }

    def _schedule_click_notification_mentions_tab(self) -> str:
        """Schedule a click on mentions tab after evaluate returns."""
        clicked_text = self._evaluate("""
            (() => {
                const keywordSet = new Set([
                    "评论和@",
                    "评论和 @",
                    "评论与@",
                    "提到我的",
                    "@我的",
                    "mentions",
                ]);
                const selectors = [
                    "[role='tab']",
                    "button",
                    "a",
                    "div[class*='tab']",
                    "div[class*='menu-item']",
                    "li[class*='tab-item']",
                    "li[class*='tab']",
                ];
                const seen = new Set();
                const candidates = [];
                for (const selector of selectors) {
                    const nodes = document.querySelectorAll(selector);
                    for (const node of nodes) {
                        if (!(node instanceof HTMLElement)) {
                            continue;
                        }
                        if (node.offsetParent === null) {
                            continue;
                        }
                        if (seen.has(node)) {
                            continue;
                        }
                        seen.add(node);
                        candidates.push(node);
                    }
                }

                for (const node of candidates) {
                    const text = (node.innerText || node.textContent || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                    if (!text) {
                        continue;
                    }
                    if (text.length > 24) {
                        continue;
                    }
                    const normalized = text.replace(/\\d+/g, "").replace(/\\s+/g, "");
                    const exactMatches = [
                        normalized,
                        text.replace(/\\d+/g, "").trim(),
                    ];
                    if (!exactMatches.some((candidate) => keywordSet.has(candidate))) {
                        continue;
                    }
                    window.setTimeout(() => {
                        try {
                            node.click();
                        } catch (error) {
                            // ignored
                        }
                    }, 80);
                    return text;
                }
                return "";
            })()
        """)
        if isinstance(clicked_text, str):
            return clicked_text.strip()
        return ""

    def _fetch_notification_mentions_via_page(self) -> dict[str, Any] | None:
        """Fetch mentions API directly in page context using logged-in cookies."""
        result = self._evaluate("""
            (() => fetch(
                "https://edith.xiaohongshu.com/api/sns/web/v1/you/mentions?num=20&cursor=",
                {
                    method: "GET",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json, text/plain, */*",
                    },
                }
            ).then(async (resp) => {
                const text = await resp.text();
                return {
                    ok: resp.ok,
                    status: resp.status,
                    url: resp.url,
                    body: text,
                };
            }).catch((error) => {
                return {
                    ok: false,
                    error: String(error),
                };
            }))()
        """)
        if not isinstance(result, dict):
            return None
        if not result.get("ok"):
            return None
        if int(result.get("status", 0)) != 200:
            return None
        body = result.get("body")
        if not isinstance(body, str) or not body.strip():
            return None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        data = payload.get("data")
        items: list[Any] = []
        if isinstance(data, dict):
            for key in ("message_list", "items", "mentions", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break

        return {
            "request_url": result.get("url") or (
                "https://edith.xiaohongshu.com/api/sns/web/v1/you/mentions?num=20&cursor="
            ),
            "count": len(items),
            "has_more": data.get("has_more") if isinstance(data, dict) else None,
            "cursor": data.get("cursor") if isinstance(data, dict) else None,
            "items": items,
            "raw_payload": payload,
            "capture_mode": "page_fetch",
        }

    def get_notification_mentions(self, wait_seconds: float = 18.0) -> dict[str, Any]:
        """
        Capture notification mentions API payload from notification page requests.

        The API is captured from real browser traffic to preserve platform
        signatures/cookies generated by page scripts.
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")
        wait_seconds = max(5.0, float(wait_seconds))

        self._send("Page.enable")
        self._send("Network.enable", {"maxPostDataSize": 65536})
        self._send("Network.setCacheDisabled", {"cacheDisabled": True})
        self._send("Page.navigate", {"url": XHS_NOTIFICATION_URL})
        self._sleep(1.2, minimum_seconds=0.5)

        direct_payload = self._fetch_notification_mentions_via_page()
        if direct_payload is not None:
            return direct_payload

        clicked_tab = self._schedule_click_notification_mentions_tab()
        if clicked_tab:
            print(f"[cdp_publish] Notification tab clicked: {clicked_tab}")

        request_meta_by_id: dict[str, dict[str, str]] = {}
        target_request_id = ""
        target_request_url = ""
        deadline = time.time() + wait_seconds

        while time.time() < deadline:
            timeout = min(1.0, max(0.1, deadline - time.time()))
            try:
                raw = self.ws.recv(timeout=timeout)
            except TimeoutError:
                continue

            message = json.loads(raw)
            method = message.get("method")
            params = message.get("params", {})

            if method == "Network.requestWillBeSent":
                request_id = params.get("requestId")
                request = params.get("request", {})
                if isinstance(request_id, str):
                    request_meta_by_id[request_id] = {
                        "url": request.get("url", ""),
                        "method": str(request.get("method", "")).upper(),
                    }
                continue

            if method == "Network.responseReceived":
                request_id = params.get("requestId")
                if not isinstance(request_id, str):
                    continue

                request_meta = request_meta_by_id.get(request_id, {})
                request_url = request_meta.get("url", "")
                if XHS_NOTIFICATION_MENTIONS_API_PATH not in request_url:
                    continue

                if request_meta.get("method") == "OPTIONS":
                    continue

                status = params.get("response", {}).get("status")
                if status != 200:
                    raise CDPError(
                        "Notification mentions API responded with non-200 status: "
                        f"{status}, url={request_url}"
                    )

                target_request_id = request_id
                target_request_url = request_url
                break

        if not target_request_id:
            raise CDPError(
                "Timed out waiting for notification mentions request. "
                "Please open notification page manually and retry."
            )

        body_result = self._send("Network.getResponseBody", {"requestId": target_request_id})
        body_text = body_result.get("body", "")
        if body_result.get("base64Encoded"):
            body_text = base64.b64decode(body_text).decode("utf-8", errors="replace")

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as e:
            raise CDPError(
                "Failed to decode notification mentions API JSON: "
                f"{e}; preview={body_text[:300]}"
            ) from e

        if not isinstance(payload, dict):
            raise CDPError("Unexpected notification mentions payload structure.")

        data = payload.get("data")
        items: list[Any] = []
        if isinstance(data, dict):
            for key in ("message_list", "items", "mentions", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break

        return {
            "request_url": target_request_url,
            "count": len(items),
            "has_more": data.get("has_more") if isinstance(data, dict) else None,
            "cursor": data.get("cursor") if isinstance(data, dict) else None,
            "items": items,
            "raw_payload": payload,
            "capture_mode": "network_capture",
        }

    def get_content_data(
        self,
        page_num: int = 1,
        page_size: int = 10,
        note_type: int = 0,
    ) -> dict[str, Any]:
        """
        Fetch creator content data table from data-analysis API.

        Args:
            page_num: Page number (1-based).
            page_size: Rows per page.
            note_type: API type filter value (default: 0).
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")
        if page_num < 1:
            raise CDPError("--page-num must be >= 1.")
        if page_size < 1:
            raise CDPError("--page-size must be >= 1.")
        # Important: direct fetch to this API can be rejected (e.g. 406) when
        # anti-bot headers are not present. We therefore capture the real
        # browser request generated by page scripts and read response body via CDP.
        self._send("Page.enable")
        self._send("Network.enable", {"maxPostDataSize": 65536})
        self._send("Page.navigate", {"url": XHS_CONTENT_DATA_URL})

        request_url_by_id: dict[str, str] = {}
        target_request_id = ""
        target_request_url = ""
        deadline = time.time() + 18

        while time.time() < deadline:
            timeout = min(1.0, max(0.1, deadline - time.time()))
            try:
                raw = self.ws.recv(timeout=timeout)
            except TimeoutError:
                continue

            message = json.loads(raw)
            method = message.get("method")
            params = message.get("params", {})

            if method == "Network.requestWillBeSent":
                request_id = params.get("requestId")
                request = params.get("request", {})
                if isinstance(request_id, str):
                    request_url_by_id[request_id] = request.get("url", "")
                continue

            if method == "Network.responseReceived":
                request_id = params.get("requestId")
                if not isinstance(request_id, str):
                    continue

                request_url = request_url_by_id.get(request_id, "")
                if XHS_CONTENT_DATA_API_PATH not in request_url:
                    continue

                status = params.get("response", {}).get("status")
                if status != 200:
                    raise CDPError(
                        "Content data API responded with non-200 status: "
                        f"{status}, url={request_url}"
                    )

                target_request_id = request_id
                target_request_url = request_url
                break

        if not target_request_id:
            raise CDPError(
                "Timed out waiting for content data request. "
                "Please open data-analysis page manually and retry."
            )

        body_result = self._send("Network.getResponseBody", {"requestId": target_request_id})
        body_text = body_result.get("body", "")
        if body_result.get("base64Encoded"):
            body_text = base64.b64decode(body_text).decode("utf-8", errors="replace")

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as e:
            raise CDPError(
                "Failed to decode content data API JSON: "
                f"{e}; preview={body_text[:300]}"
            ) from e

        if not isinstance(payload, dict):
            raise CDPError("Unexpected content data payload structure.")

        data = payload.get("data")
        note_infos = data.get("note_infos") if isinstance(data, dict) else []
        if not isinstance(note_infos, list):
            note_infos = []
        rows = _map_note_infos_to_content_rows(note_infos)

        query = parse_qs(urlparse(target_request_url).query)
        resolved_page_num = int((query.get("page_num") or ["1"])[0])
        resolved_page_size = int((query.get("page_size") or ["10"])[0])
        resolved_type = int((query.get("type") or ["0"])[0])

        if (
            page_num != resolved_page_num
            or page_size != resolved_page_size
            or note_type != resolved_type
        ):
            print(
                "[cdp_publish] Warning: Requested pagination/filter differs from "
                "captured page request. Returning captured data instead."
            )

        return {
            "request_url": target_request_url,
            "requested_page_num": page_num,
            "requested_page_size": page_size,
            "requested_type": note_type,
            "resolved_page_num": resolved_page_num,
            "resolved_page_size": resolved_page_size,
            "resolved_type": resolved_type,
            "total": data.get("total") if isinstance(data, dict) else None,
            "count_returned": len(rows),
            "rows": rows,
        }

    # ------------------------------------------------------------------
    # Publishing actions
    # ------------------------------------------------------------------

    def _click_tab(self, tab_selector: str, tab_text: str):
        """Click a publish-mode tab by selector and text content."""
        print(f"[cdp_publish] Clicking '{tab_text}' tab...")
        selector_alt = (
            "div.creator-tab, .creator-tab, [class*='creator-tab'], [role='tab'], button, div"
        )
        selector_alt_literal = json.dumps(selector_alt)
        tab_text_literal = json.dumps(tab_text)

        clicked = self._evaluate(f"""
            (function() {{
                var targetText = {tab_text_literal};
                var fuzzyKeywords = [targetText];
                if (targetText.indexOf('图文') !== -1) {{
                    fuzzyKeywords.push('图文', '上传图文');
                }}
                if (targetText.indexOf('视频') !== -1) {{
                    fuzzyKeywords.push('视频', '上传视频');
                }}

                function matches(text) {{
                    var t = (text || '').trim();
                    if (!t) return false;
                    if (t === targetText) return true;
                    for (var i = 0; i < fuzzyKeywords.length; i++) {{
                        var keyword = fuzzyKeywords[i];
                        if (keyword && t.indexOf(keyword) !== -1) {{
                            return true;
                        }}
                    }}
                    return false;
                }}

                var tabs = document.querySelectorAll('{tab_selector}');
                for (var i = 0; i < tabs.length; i++) {{
                    if (matches(tabs[i].textContent)) {{
                        tabs[i].click();
                        return true;
                    }}
                }}

                var allTabs = document.querySelectorAll({selector_alt_literal});
                for (var j = 0; j < allTabs.length; j++) {{
                    if (matches(allTabs[j].textContent)) {{
                        allTabs[j].click();
                        return true;
                    }}
                }}
                return false;
            }})();
        """)

        if not clicked:
            if "图文" in tab_text:
                upload_ready = self._evaluate(
                    f"!!document.querySelector('{SELECTORS['upload_input']}') || "
                    f"!!document.querySelector('{SELECTORS['upload_input_alt']}')"
                )
                if upload_ready:
                    print(
                        "[cdp_publish] '上传图文' tab not found, but upload input is ready. "
                        "Continuing..."
                    )
                    return

            raise CDPError(
                f"Could not find '{tab_text}' tab. "
                "The page structure may have changed."
            )

        print(f"[cdp_publish] Tab '{tab_text}' clicked, waiting for upload area...")
        self._sleep(TAB_CLICK_WAIT, minimum_seconds=0.8)

    def _click_image_text_tab(self):
        """Click the '上传图文' tab to switch to image+text publish mode."""
        self._click_tab(SELECTORS["image_text_tab"], SELECTORS["image_text_tab_text"])

    def _click_video_tab(self):
        """Click the '上传视频' tab to switch to video publish mode."""
        self._click_tab(SELECTORS["video_tab"], SELECTORS["video_tab_text"])

    def _upload_images(self, image_paths: list[str]):
        """Upload images via the file input element."""
        if not image_paths:
            print("[cdp_publish] No images to upload, skipping.")
            return

        # Normalize paths (forward slashes for CDP)
        normalized = [p.replace("\\", "/") for p in image_paths]

        print(f"[cdp_publish] Uploading {len(image_paths)} image(s)...")

        # Enable DOM domain
        self._send("DOM.enable")

        # Get the document root
        doc = self._send("DOM.getDocument")
        root_id = doc["root"]["nodeId"]

        # Try primary selector, then fallback
        node_id = 0
        for selector in (SELECTORS["upload_input"], SELECTORS["upload_input_alt"]):
            result = self._send("DOM.querySelector", {
                "nodeId": root_id,
                "selector": selector,
            })
            node_id = result.get("nodeId", 0)
            if node_id:
                break

        if not node_id:
            raise CDPError(
                "Could not find file input element.\n"
                "The page structure may have changed. Check references/publish-workflow.md."
            )

        # Use DOM.setFileInputFiles to set the files
        self._send("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": normalized,
        })

        print("[cdp_publish] Images uploaded. Waiting for editor to appear...")
        self._sleep(UPLOAD_WAIT, minimum_seconds=2.0)

    def _upload_video(self, video_path: str):
        """Upload a video file via the file input element."""
        normalized = video_path.replace("\\", "/")
        print(f"[cdp_publish] Uploading video: {normalized}")

        # Enable DOM domain
        self._send("DOM.enable")

        # Get the document root
        doc = self._send("DOM.getDocument")
        root_id = doc["root"]["nodeId"]

        # Find the file input for video upload
        node_id = 0
        for selector in (SELECTORS["upload_input"], SELECTORS["upload_input_alt"]):
            result = self._send("DOM.querySelector", {
                "nodeId": root_id,
                "selector": selector,
            })
            node_id = result.get("nodeId", 0)
            if node_id:
                break

        if not node_id:
            raise CDPError(
                "Could not find file input element for video upload.\n"
                "The page structure may have changed."
            )

        # Set the video file
        self._send("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": [normalized],
        })

        print("[cdp_publish] Video file submitted. Waiting for processing...")

    def _wait_video_processing(self):
        """Wait for the video to finish processing after upload.

        The Xiaohongshu creator page shows a progress/processing indicator
        while the video is being uploaded and transcoded. We wait until the
        title input or content editor becomes available, which signals
        that the video has been processed.
        """
        print("[cdp_publish] Waiting for video processing to complete...")
        deadline = time.time() + VIDEO_PROCESS_TIMEOUT
        last_pct = ""

        while time.time() < deadline:
            # Check if the title input has appeared (signals processing done)
            for selector in (SELECTORS["title_input"], SELECTORS["title_input_alt"]):
                found = self._evaluate(f"!!document.querySelector('{selector}')")
                if found:
                    print("[cdp_publish] Video processing complete - editor is ready.")
                    time.sleep(1)  # small extra buffer
                    return

            # Try to read progress text for user feedback
            pct = self._evaluate("""
                (function() {
                    // Look for progress percentage text
                    var els = document.querySelectorAll(
                        '[class*="progress"], [class*="percent"], [class*="upload"]'
                    );
                    for (var i = 0; i < els.length; i++) {
                        var t = els[i].textContent.trim();
                        if (t && /\\d+%/.test(t)) return t;
                    }
                    return '';
                })()
            """) or ""
            if pct and pct != last_pct:
                print(f"[cdp_publish] Video processing: {pct}")
                last_pct = pct

            time.sleep(VIDEO_PROCESS_POLL)

        raise CDPError(
            f"Video processing did not complete within {VIDEO_PROCESS_TIMEOUT}s. "
            "The video may be too large or processing is slow."
        )

    def _fill_title(self, title: str):
        """Fill in the article title."""
        print(f"[cdp_publish] Setting title: {title[:40]}...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        for selector in (SELECTORS["title_input"], SELECTORS["title_input_alt"]):
            found = self._evaluate(f"!!document.querySelector('{selector}')")
            if found:
                escaped_title = json.dumps(title)
                self._evaluate(f"""
                    (function() {{
                        var el = document.querySelector('{selector}');
                        var nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        el.focus();
                        nativeSetter.call(el, {escaped_title});
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }})();
                """)
                print("[cdp_publish] Title set.")
                return

        raise CDPError("Could not find title input element.")

    def _fill_content(self, content: str):
        """Fill in the article body content using the TipTap/ProseMirror editor."""
        print(f"[cdp_publish] Setting content ({len(content)} chars)...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        for selector in (SELECTORS["content_editor"], SELECTORS["content_editor_alt"]):
            found = self._evaluate(f"!!document.querySelector('{selector}')")
            if found:
                escaped = json.dumps(content)
                self._evaluate(f"""
                    (function() {{
                        var el = document.querySelector('{selector}');
                        el.focus();
                        var text = {escaped};
                        var paragraphs = text.split('\\n').filter(function(p) {{ return p.trim(); }});
                        var html = [];
                        for (var i = 0; i < paragraphs.length; i++) {{
                            html.push('<p>' + paragraphs[i] + '</p>');
                            if (i < paragraphs.length - 1) {{
                                html.push('<p><br></p>');
                            }}
                        }}
                        el.innerHTML = html.join('');
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }})();
                """)
                print("[cdp_publish] Content set.")
                return

        raise CDPError("Could not find content editor element.")

    def _like_note(self):
        """Like the current note."""
        print("[cdp_publish] Liking note...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        liked = self._evaluate("""
            (function() {{
                // Try various like button selectors
                var selectors = [
                    '.like-button, [class*="like"], [class*="heart"]',
                    'button[aria-label*="like"], button[aria-label*="赞"]',
                    '[data-testid*="like"], [data-testid*="heart"]',
                    'svg[class*="like"], svg[class*="heart"]'
                ];

                for (var sel of selectors) {{
                    var elements = document.querySelectorAll(sel);
                    for (var el of elements) {{
                        // Check if it's not already liked
                        if (!el.classList.contains('liked') && !el.classList.contains('active')) {{
                            el.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }})();
        """)

        if liked:
            print("[cdp_publish] Note liked.")
        else:
            print("[cdp_publish] Could not find like button or already liked.")

        return liked

    def _collect_note(self):
        """Collect the current note."""
        print("[cdp_publish] Collecting note...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        collected = self._evaluate("""
            (function() {{
                // Try various collect button selectors
                var selectors = [
                    '.collect-button, [class*="collect"], [class*="bookmark"]',
                    'button[aria-label*="collect"], button[aria-label*="收藏"]',
                    '[data-testid*="collect"], [data-testid*="bookmark"]',
                    'svg[class*="collect"], svg[class*="bookmark"]'
                ];

                for (var sel of selectors) {{
                    var elements = document.querySelectorAll(sel);
                    for (var el of elements) {{
                        // Check if it's not already collected
                        if (!el.classList.contains('collected') && !el.classList.contains('active')) {{
                            el.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }})();
        """)

        if collected:
            print("[cdp_publish] Note collected.")
        else:
            print("[cdp_publish] Could not find collect button or already collected.")

        return collected

    def _move_mouse(self, x: float, y: float):
        """Move mouse cursor via CDP to support hover-driven UI."""
        self._send("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": float(x),
            "y": float(y),
        })

    def _click_mouse(self, x: float, y: float):
        """Perform a real left-click via CDP at the given coordinates."""
        for event_type in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": float(x),
                "y": float(y),
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.05)

    def _click_element_by_cdp(self, description: str, js_get_rect: str):
        """Click an element using CDP Input.dispatchMouseEvent for reliable clicks.

        Modern web frameworks (Vue/React) often ignore JS .click() calls.
        Dispatching real mouse events via CDP always works.

        Args:
            description: Human-readable description for logging.
            js_get_rect: JavaScript expression that returns {x, y, width, height}
                         of the element to click, or null if not found.
        """
        rect = self._evaluate(js_get_rect)
        if not rect:
            raise CDPError(
                f"Could not find {description}. "
                "Please click it manually in the browser."
            )

        # Compute center of the element
        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2
        print(f"[cdp_publish] Clicking {description} at ({cx:.0f}, {cy:.0f})...")

        # Dispatch a full mouse click sequence via CDP
        for event_type in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": cx,
                "y": cy,
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Screenshot and scroll infrastructure
    # ------------------------------------------------------------------

    def capture_screenshot(
        self, output_path: str | None = None, quality: int = 80
    ) -> dict[str, Any]:
        """Capture a screenshot of the current page via CDP.

        Args:
            output_path: Optional file path to save the screenshot.
                         If None, saves to tmp/screenshots/ with timestamp.
            quality: JPEG quality 1-100 (default: 80).

        Returns:
            {"success": True, "path": "/abs/path/screenshot.jpg", "base64_length": N}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        result = self._send("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "fromSurface": True,
        })
        image_data = result.get("data", "")
        if not image_data:
            return {"success": False, "error": "Empty screenshot data"}

        if output_path:
            abs_path = os.path.abspath(output_path)
        else:
            screenshot_dir = os.path.abspath(
                os.path.join(SCRIPT_DIR, "..", "tmp", "screenshots")
            )
            os.makedirs(screenshot_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            abs_path = os.path.join(screenshot_dir, f"screenshot_{timestamp}.jpg")

        with open(abs_path, "wb") as f:
            f.write(base64.b64decode(image_data))

        print(f"[cdp_publish] Screenshot saved to {abs_path}")
        return {
            "success": True,
            "path": abs_path,
            "base64_length": len(image_data),
        }

    def _scroll_page(
        self, direction: str = "down", distance: int = 600
    ) -> dict[str, Any]:
        """Scroll the current page with human-like behavior.

        Args:
            direction: "down" or "up".
            distance: Total pixels to scroll.

        Returns:
            {"scrollY_before": N, "scrollY_after": M, "scrollHeight": H,
             "clientHeight": C, "at_bottom": bool}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        sign = 1 if direction == "down" else -1
        # Split into 2-3 smaller scrolls for human-like behavior
        steps = random.randint(2, 3)
        step_distance = distance // steps

        before_info = self._evaluate("""
            (function() {
                return {
                    scrollY: window.scrollY,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight
                };
            })();
        """)

        for i in range(steps):
            d = step_distance * sign
            if i == steps - 1:
                # Last step takes the remainder
                d = (distance - step_distance * (steps - 1)) * sign
            self._evaluate(f"window.scrollBy({{top: {d}, behavior: 'smooth'}});")
            self._sleep(0.3, minimum_seconds=0.15)

        # Wait for lazy-loaded content to render
        self._sleep(1.5, minimum_seconds=0.8)

        after_info = self._evaluate("""
            (function() {
                return {
                    scrollY: window.scrollY,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight
                };
            })();
        """)

        at_bottom = (
            after_info["scrollY"] + after_info["clientHeight"]
            >= after_info["scrollHeight"] - 5
        )

        return {
            "scrollY_before": before_info.get("scrollY", 0),
            "scrollY_after": after_info.get("scrollY", 0),
            "scrollHeight": after_info.get("scrollHeight", 0),
            "clientHeight": after_info.get("clientHeight", 0),
            "at_bottom": at_bottom,
        }

    # ------------------------------------------------------------------
    # Browsing: home feed, following feed, user profile, note detail
    # ------------------------------------------------------------------

    def _extract_feeds_from_page(self) -> list[dict[str, Any]]:
        """Extract feed items from the current page via __INITIAL_STATE__ or DOM."""
        # Strategy 1: __INITIAL_STATE__
        feeds_json = self._evaluate("""
            (function() {
                var state = window.__INITIAL_STATE__;
                if (!state) return '[]';
                var candidates = [
                    state.home && state.home.feeds,
                    state.homeFeed && state.homeFeed.feeds,
                    state.explore && state.explore.feeds,
                    state.feed && state.feed.feeds,
                ];
                for (var i = 0; i < candidates.length; i++) {
                    var f = candidates[i];
                    if (!f) continue;
                    var arr = f.value || f._value || f;
                    if (Array.isArray(arr) && arr.length > 0) {
                        return JSON.stringify(arr.map(function(item) {
                            var note = item.noteCard || item.note_card || item;
                            var user = note.user || item.user || {};
                            return {
                                note_id: item.id || note.noteId || note.note_id || '',
                                xsec_token: item.xsec_token || item.xsecToken || '',
                                title: note.displayTitle || note.display_title || note.title || '',
                                author: user.nickName || user.nickname || user.nick_name || '',
                                author_id: user.userId || user.user_id || '',
                                cover_url: (note.cover && (note.cover.urlDefault || note.cover.url)) || '',
                                like_count: (note.interactInfo && note.interactInfo.likedCount) || '',
                                type: note.type || ''
                            };
                        }));
                    }
                }
                return '[]';
            })();
        """)

        feeds = []
        if feeds_json and feeds_json != "[]":
            try:
                feeds = json.loads(feeds_json)
            except (json.JSONDecodeError, TypeError):
                pass

        if feeds:
            return feeds

        # Strategy 2: DOM fallback
        dom_json = self._evaluate("""
            (function() {
                var cards = document.querySelectorAll(
                    'section.note-item, [class*="note-item"], a[href*="/explore/"]'
                );
                var results = [];
                var seen = {};
                for (var i = 0; i < cards.length; i++) {
                    var card = cards[i];
                    var link = card.tagName === 'A' ? card :
                        (card.querySelector('a[href*="/explore/"]') ||
                         card.closest('a[href*="/explore/"]'));
                    if (!link) continue;
                    var href = link.getAttribute('href') || '';
                    var match = href.match(/explore\\/([a-f0-9]+)/);
                    var noteId = match ? match[1] : '';
                    if (!noteId || seen[noteId]) continue;
                    seen[noteId] = true;
                    var search = '';
                    try { search = new URL(link.href, location.origin).search; } catch(e) {}
                    var params = new URLSearchParams(search);
                    var titleEl = card.querySelector('[class*="title"], .title, span.title');
                    var authorEl = card.querySelector('[class*="author"], .author-wrapper .name, .nickname');
                    var likeEl = card.querySelector('[class*="like-count"], .count, [class*="like"] .count');
                    var coverEl = card.querySelector('img');
                    results.push({
                        note_id: noteId,
                        xsec_token: params.get('xsec_token') || '',
                        title: (titleEl && titleEl.textContent || '').trim(),
                        author: (authorEl && authorEl.textContent || '').trim(),
                        author_id: '',
                        cover_url: (coverEl && coverEl.src) || '',
                        like_count: (likeEl && likeEl.textContent || '').trim(),
                        type: ''
                    });
                }
                return JSON.stringify(results);
            })();
        """)

        if dom_json:
            try:
                feeds = json.loads(dom_json)
            except (json.JSONDecodeError, TypeError):
                pass

        return feeds

    def browse_home_feed(
        self,
        max_items: int = 20,
        scroll_count: int = 3,
        take_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Browse the Xiaohongshu explore/home feed.

        Args:
            max_items: Maximum feed items to extract.
            scroll_count: Number of scroll iterations for more content.
            take_screenshot: Capture screenshot after loading.

        Returns:
            {"url": "...", "feed_count": N, "feeds": [...], "screenshot_path": ...}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        print("[cdp_publish] Browsing home feed...")
        self._navigate(XHS_EXPLORE_URL)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.5)

        all_feeds: dict[str, dict] = {}

        # Initial extraction
        for item in self._extract_feeds_from_page():
            nid = item.get("note_id")
            if nid and nid not in all_feeds:
                all_feeds[nid] = item

        # Scroll for more content
        for i in range(scroll_count):
            if len(all_feeds) >= max_items:
                break
            print(f"[cdp_publish] Scrolling ({i + 1}/{scroll_count})...")
            scroll_result = self._scroll_page(direction="down", distance=800)
            for item in self._extract_feeds_from_page():
                nid = item.get("note_id")
                if nid and nid not in all_feeds:
                    all_feeds[nid] = item
            if scroll_result.get("at_bottom"):
                print("[cdp_publish] Reached bottom of page.")
                break

        feeds_list = list(all_feeds.values())[:max_items]
        screenshot_path = None
        if take_screenshot:
            ss = self.capture_screenshot()
            screenshot_path = ss.get("path")

        print(f"[cdp_publish] Found {len(feeds_list)} feed items.")
        return {
            "url": XHS_EXPLORE_URL,
            "feed_count": len(feeds_list),
            "feeds": feeds_list,
            "screenshot_path": screenshot_path,
        }

    def browse_following_feed(
        self,
        max_items: int = 20,
        scroll_count: int = 3,
        take_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Browse the following feed (content from followed users).

        Args:
            max_items: Maximum feed items to extract.
            scroll_count: Number of scroll iterations.
            take_screenshot: Capture screenshot after loading.

        Returns:
            {"url": "...", "feed_count": N, "feeds": [...], "screenshot_path": ...}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        print("[cdp_publish] Browsing following feed...")
        self._navigate(XHS_FOLLOWING_FEED_URL)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.5)

        # Try clicking the "关注" tab as a fallback if URL param doesn't work
        self._evaluate("""
            (function() {
                var tabs = document.querySelectorAll(
                    '[class*="channel"] [class*="tab"], [class*="tab-item"], [class*="channel-item"]'
                );
                for (var i = 0; i < tabs.length; i++) {
                    var text = (tabs[i].textContent || '').trim();
                    if (text === '关注' || text === 'Following') {
                        tabs[i].click();
                        return true;
                    }
                }
                return false;
            })();
        """)
        self._sleep(2, minimum_seconds=1.0)

        all_feeds: dict[str, dict] = {}

        for item in self._extract_feeds_from_page():
            nid = item.get("note_id")
            if nid and nid not in all_feeds:
                all_feeds[nid] = item

        for i in range(scroll_count):
            if len(all_feeds) >= max_items:
                break
            print(f"[cdp_publish] Scrolling ({i + 1}/{scroll_count})...")
            scroll_result = self._scroll_page(direction="down", distance=800)
            for item in self._extract_feeds_from_page():
                nid = item.get("note_id")
                if nid and nid not in all_feeds:
                    all_feeds[nid] = item
            if scroll_result.get("at_bottom"):
                print("[cdp_publish] Reached bottom of page.")
                break

        feeds_list = list(all_feeds.values())[:max_items]
        screenshot_path = None
        if take_screenshot:
            ss = self.capture_screenshot()
            screenshot_path = ss.get("path")

        print(f"[cdp_publish] Found {len(feeds_list)} following feed items.")
        return {
            "url": XHS_FOLLOWING_FEED_URL,
            "feed_count": len(feeds_list),
            "feeds": feeds_list,
            "screenshot_path": screenshot_path,
        }

    def view_user_profile(
        self,
        user_id: str,
        max_notes: int = 20,
        scroll_count: int = 2,
        take_screenshot: bool = False,
    ) -> dict[str, Any]:
        """View a user's profile and their notes list.

        Args:
            user_id: Xiaohongshu user ID.
            max_notes: Maximum notes to extract.
            scroll_count: Number of scroll iterations.
            take_screenshot: Capture screenshot.

        Returns:
            {"user_id": "...", "user_info": {...}, "notes_count": N,
             "notes": [...], "screenshot_path": ...}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        url = XHS_USER_PROFILE_URL_TEMPLATE.format(user_id=user_id.strip())
        print(f"[cdp_publish] Viewing user profile: {url}")
        self._navigate(url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=2.0)

        # Extract user info from __INITIAL_STATE__
        user_json = self._evaluate("""
            (function() {
                var state = window.__INITIAL_STATE__;
                if (!state || !state.user) return '{}';
                var u = state.user.userPageData || state.user;
                if (!u) return '{}';
                var basicInfo = u.basicInfo || u;
                var interactions = u.interactions || [];
                var interMap = {};
                if (Array.isArray(interactions)) {
                    for (var i = 0; i < interactions.length; i++) {
                        var item = interactions[i];
                        interMap[item.type || item.name || ''] = item.count || 0;
                    }
                }
                return JSON.stringify({
                    nickname: basicInfo.nickname || basicInfo.nickName || '',
                    avatar: basicInfo.imageb || basicInfo.image || basicInfo.avatar || '',
                    red_id: basicInfo.redId || basicInfo.red_id || '',
                    description: basicInfo.desc || basicInfo.description || '',
                    ip_location: basicInfo.ipLocation || '',
                    gender: basicInfo.gender || '',
                    follows: interMap.follows || u.follows || 0,
                    fans: interMap.fans || u.fans || 0,
                    interaction: interMap.interaction || u.interaction || 0,
                });
            })();
        """)

        user_info = {}
        if user_json:
            try:
                user_info = json.loads(user_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # Extract notes
        notes_json = self._evaluate("""
            (function() {
                var state = window.__INITIAL_STATE__;
                if (!state || !state.user) return '[]';
                var notes = state.user.notes;
                if (!notes) return '[]';
                var arr = notes.value || notes._value || notes;
                if (!Array.isArray(arr)) {
                    // Try flat array structure
                    arr = state.user.noteList || state.user.note_list || [];
                }
                if (!Array.isArray(arr)) return '[]';
                return JSON.stringify(arr.slice(0, 50).map(function(item) {
                    var note = item.noteCard || item.note_card || item;
                    return {
                        note_id: item.id || item.noteId || note.noteId || '',
                        xsec_token: item.xsec_token || item.xsecToken || '',
                        title: note.displayTitle || note.display_title || note.title || '',
                        cover_url: (note.cover && (note.cover.urlDefault || note.cover.url)) || '',
                        like_count: (note.interactInfo && note.interactInfo.likedCount) || '',
                        type: note.type || ''
                    };
                }));
            })();
        """)

        notes = []
        if notes_json:
            try:
                notes = json.loads(notes_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # Scroll for more notes
        all_note_ids = {n["note_id"] for n in notes if n.get("note_id")}
        for i in range(scroll_count):
            if len(notes) >= max_notes:
                break
            print(f"[cdp_publish] Scrolling for more notes ({i + 1}/{scroll_count})...")
            scroll_result = self._scroll_page(direction="down", distance=600)
            # Re-extract after scroll (DOM-based)
            more_json = self._evaluate("""
                (function() {
                    var cards = document.querySelectorAll(
                        'section.note-item, [class*="note-item"], a[href*="/explore/"]'
                    );
                    var results = [];
                    for (var i = 0; i < cards.length; i++) {
                        var card = cards[i];
                        var link = card.tagName === 'A' ? card :
                            (card.querySelector('a[href*="/explore/"]') ||
                             card.closest('a[href*="/explore/"]'));
                        if (!link) continue;
                        var href = link.getAttribute('href') || '';
                        var match = href.match(/explore\\/([a-f0-9]+)/);
                        var noteId = match ? match[1] : '';
                        if (!noteId) continue;
                        var search = '';
                        try { search = new URL(link.href, location.origin).search; } catch(e) {}
                        var params = new URLSearchParams(search);
                        var titleEl = card.querySelector('[class*="title"], .title');
                        var coverEl = card.querySelector('img');
                        var likeEl = card.querySelector('[class*="like-count"], [class*="like"] .count');
                        results.push({
                            note_id: noteId,
                            xsec_token: params.get('xsec_token') || '',
                            title: (titleEl && titleEl.textContent || '').trim(),
                            cover_url: (coverEl && coverEl.src) || '',
                            like_count: (likeEl && likeEl.textContent || '').trim(),
                            type: ''
                        });
                    }
                    return JSON.stringify(results);
                })();
            """)
            if more_json:
                try:
                    more_notes = json.loads(more_json)
                    for n in more_notes:
                        nid = n.get("note_id")
                        if nid and nid not in all_note_ids:
                            all_note_ids.add(nid)
                            notes.append(n)
                except (json.JSONDecodeError, TypeError):
                    pass
            if scroll_result.get("at_bottom"):
                break

        notes = notes[:max_notes]

        screenshot_path = None
        if take_screenshot:
            # Scroll back to top for profile screenshot
            self._evaluate("window.scrollTo({top: 0, behavior: 'smooth'});")
            self._sleep(0.5, minimum_seconds=0.3)
            ss = self.capture_screenshot()
            screenshot_path = ss.get("path")

        print(f"[cdp_publish] User profile: {user_info.get('nickname', '?')}, {len(notes)} notes.")
        return {
            "user_id": user_id,
            "url": url,
            "user_info": user_info,
            "notes_count": len(notes),
            "notes": notes,
            "screenshot_path": screenshot_path,
        }

    def read_note_detail(
        self,
        feed_id: str,
        xsec_token: str,
        take_screenshot: bool = False,
    ) -> dict[str, Any]:
        """Read a note's full content, images, and comments in a clean structure.

        Args:
            feed_id: Note/feed ID.
            xsec_token: Security token.
            take_screenshot: Capture screenshot.

        Returns:
            {"feed_id": "...", "title": "...", "content": "...", "author": {...},
             "images": [...], "video_url": ..., "stats": {...},
             "publish_time": "...", "tags": [...], "comments": [...],
             "screenshot_path": ...}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        # Use existing get_feed_detail for raw data
        raw_detail = self.get_feed_detail(feed_id=feed_id, xsec_token=xsec_token)

        # Post-process into clean structure
        note = raw_detail if isinstance(raw_detail, dict) else {}
        note_data = note.get("note", note)

        # Extract basic info
        title = note_data.get("title", "")
        desc = note_data.get("desc", "")

        # Author
        user_data = note_data.get("user", {})
        author = {
            "nickname": user_data.get("nickName", user_data.get("nickname", "")),
            "user_id": user_data.get("userId", user_data.get("user_id", "")),
            "avatar": user_data.get("avatar", ""),
        }

        # Images
        image_list = note_data.get("imageList", note_data.get("image_list", []))
        images = []
        for img in (image_list or []):
            url_val = ""
            if isinstance(img, dict):
                url_val = (
                    img.get("urlDefault")
                    or img.get("url_default")
                    or img.get("url")
                    or img.get("urlPre")
                    or ""
                )
                if not url_val:
                    info_list = img.get("infoList", img.get("info_list", []))
                    if info_list and isinstance(info_list, list):
                        url_val = info_list[-1].get("url", "")
            elif isinstance(img, str):
                url_val = img
            if url_val:
                images.append(url_val)

        # Video
        video_data = note_data.get("video", {})
        video_url = None
        if video_data and isinstance(video_data, dict):
            media = video_data.get("media", {})
            stream = media.get("stream", {}) if isinstance(media, dict) else {}
            # Try h264 first
            h264 = stream.get("h264", [])
            if h264 and isinstance(h264, list) and len(h264) > 0:
                video_url = h264[0].get("masterUrl", h264[0].get("backup_urls", [""])[0] if h264[0].get("backup_urls") else "")
            if not video_url:
                h265 = stream.get("h265", [])
                if h265 and isinstance(h265, list) and len(h265) > 0:
                    video_url = h265[0].get("masterUrl", "")

        # Stats
        interact = note_data.get("interactInfo", note_data.get("interact_info", {}))
        stats = {}
        if interact and isinstance(interact, dict):
            stats = {
                "likes": interact.get("likedCount", interact.get("liked_count", 0)),
                "collects": interact.get("collectedCount", interact.get("collected_count", 0)),
                "comments": interact.get("commentCount", interact.get("comment_count", 0)),
                "shares": interact.get("shareCount", interact.get("share_count", 0)),
            }

        # Time
        publish_time = _format_post_time(note_data.get("time"))

        # Tags
        tag_list = note_data.get("tagList", note_data.get("tag_list", []))
        tags = []
        for tag in (tag_list or []):
            if isinstance(tag, dict):
                tags.append(tag.get("name", ""))
            elif isinstance(tag, str):
                tags.append(tag)

        # Comments
        raw_comments = note_data.get("comments", [])
        comments = []
        for c in (raw_comments or []):
            if not isinstance(c, dict):
                continue
            c_user = c.get("userInfo", c.get("user_info", {}))
            comments.append({
                "author": c_user.get("nickname", c_user.get("nickName", "")) if isinstance(c_user, dict) else "",
                "content": c.get("content", ""),
                "like_count": c.get("likeCount", c.get("like_count", 0)),
                "time": _format_post_time(c.get("createTime", c.get("create_time"))),
            })

        screenshot_path = None
        if take_screenshot:
            ss = self.capture_screenshot()
            screenshot_path = ss.get("path")

        return {
            "feed_id": feed_id,
            "title": title,
            "content": desc,
            "author": author,
            "images": images,
            "video_url": video_url,
            "stats": stats,
            "publish_time": publish_time,
            "tags": tags,
            "comments": comments,
            "screenshot_path": screenshot_path,
        }

    # ------------------------------------------------------------------
    # Interaction: like, collect, follow
    # ------------------------------------------------------------------

    def like_note(self, feed_id: str, xsec_token: str) -> dict[str, Any]:
        """Like a note via CDP mouse click.

        Args:
            feed_id: Note/feed ID.
            xsec_token: Security token.

        Returns:
            {"feed_id": "...", "success": True, "action": "liked"|"already_liked"}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        detail_url = make_feed_detail_url(feed_id, xsec_token)
        print(f"[cdp_publish] Navigating to note for like: {feed_id}")
        self._navigate(detail_url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.5)

        self._check_feed_page_accessible()

        # Find like button rect and state
        btn_info = self._evaluate("""
            (function() {
                var selectors = [
                    '.engage-bar .like-wrapper',
                    '.engage-bar [class*="like"]',
                    '.note-detail .like-wrapper',
                    '[class*="interact"] [class*="like"]',
                    '.like-wrapper',
                    '[class*="like"][class*="container"]',
                ];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!(el instanceof HTMLElement) || el.offsetParent === null) continue;
                        var r = el.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;
                        var isLiked = el.classList.contains('active') ||
                                      el.classList.contains('liked') ||
                                      el.classList.contains('selected') ||
                                      (el.querySelector && el.querySelector('.active, .liked, [class*="active"]') !== null);
                        if (!isLiked) {
                            var style = getComputedStyle(el);
                            isLiked = style.color === 'rgb(255, 36, 66)' ||
                                      style.color === 'rgb(255, 72, 72)';
                        }
                        return {
                            x: r.x, y: r.y, width: r.width, height: r.height,
                            already_liked: isLiked
                        };
                    }
                }
                return null;
            })();
        """)

        if not btn_info:
            print("[cdp_publish] Could not find like button.")
            return {"feed_id": feed_id, "success": False, "action": "button_not_found"}

        if btn_info.get("already_liked"):
            print("[cdp_publish] Note already liked.")
            return {"feed_id": feed_id, "success": True, "action": "already_liked"}

        # Click via CDP
        cx = btn_info["x"] + btn_info["width"] / 2
        cy = btn_info["y"] + btn_info["height"] / 2
        print(f"[cdp_publish] Clicking like button at ({cx:.0f}, {cy:.0f})...")
        self._move_mouse(cx, cy)
        self._sleep(0.2, minimum_seconds=0.1)
        self._click_mouse(cx, cy)
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.5)

        print("[cdp_publish] Note liked.")
        return {"feed_id": feed_id, "success": True, "action": "liked"}

    def collect_note(self, feed_id: str, xsec_token: str) -> dict[str, Any]:
        """Collect/bookmark a note via CDP mouse click.

        Args:
            feed_id: Note/feed ID.
            xsec_token: Security token.

        Returns:
            {"feed_id": "...", "success": True, "action": "collected"|"already_collected"}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        detail_url = make_feed_detail_url(feed_id, xsec_token)
        print(f"[cdp_publish] Navigating to note for collect: {feed_id}")
        self._navigate(detail_url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=1.5)

        self._check_feed_page_accessible()

        btn_info = self._evaluate("""
            (function() {
                var selectors = [
                    '.engage-bar .collect-wrapper',
                    '.engage-bar [class*="collect"]',
                    '.note-detail .collect-wrapper',
                    '[class*="interact"] [class*="collect"]',
                    '.collect-wrapper',
                    '[class*="collect"][class*="container"]',
                    '[class*="star"][class*="container"]',
                ];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!(el instanceof HTMLElement) || el.offsetParent === null) continue;
                        var r = el.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;
                        var isCollected = el.classList.contains('active') ||
                                          el.classList.contains('collected') ||
                                          el.classList.contains('selected') ||
                                          (el.querySelector && el.querySelector('.active, .collected, [class*="active"]') !== null);
                        if (!isCollected) {
                            var style = getComputedStyle(el);
                            isCollected = style.color === 'rgb(255, 214, 0)' ||
                                          style.color === 'rgb(255, 203, 0)';
                        }
                        return {
                            x: r.x, y: r.y, width: r.width, height: r.height,
                            already_collected: isCollected
                        };
                    }
                }
                return null;
            })();
        """)

        if not btn_info:
            print("[cdp_publish] Could not find collect button.")
            return {"feed_id": feed_id, "success": False, "action": "button_not_found"}

        if btn_info.get("already_collected"):
            print("[cdp_publish] Note already collected.")
            return {"feed_id": feed_id, "success": True, "action": "already_collected"}

        cx = btn_info["x"] + btn_info["width"] / 2
        cy = btn_info["y"] + btn_info["height"] / 2
        print(f"[cdp_publish] Clicking collect button at ({cx:.0f}, {cy:.0f})...")
        self._move_mouse(cx, cy)
        self._sleep(0.2, minimum_seconds=0.1)
        self._click_mouse(cx, cy)
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.5)

        print("[cdp_publish] Note collected.")
        return {"feed_id": feed_id, "success": True, "action": "collected"}

    def follow_user(self, user_id: str) -> dict[str, Any]:
        """Follow a user via CDP mouse click.

        Args:
            user_id: Xiaohongshu user ID.

        Returns:
            {"user_id": "...", "success": True, "action": "followed"|"already_following"}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        url = XHS_USER_PROFILE_URL_TEMPLATE.format(user_id=user_id.strip())
        print(f"[cdp_publish] Navigating to user profile for follow: {user_id}")
        self._navigate(url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=2.0)

        btn_info = self._evaluate("""
            (function() {
                var btns = document.querySelectorAll(
                    'button, [class*="follow-btn"], [class*="follow-button"], [role="button"]'
                );
                for (var i = 0; i < btns.length; i++) {
                    var el = btns[i];
                    if (!(el instanceof HTMLElement) || el.offsetParent === null) continue;
                    var text = (el.textContent || '').replace(/\\s+/g, '').trim();
                    var r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 15) continue;
                    var isFollowing = ['已关注', '互相关注', 'Following', 'Mutual'].some(function(k) {
                        return text.indexOf(k) >= 0;
                    });
                    var isFollowBtn = ['关注', 'Follow'].some(function(k) {
                        return text.indexOf(k) >= 0;
                    }) && !isFollowing;
                    if (isFollowBtn || isFollowing) {
                        return {
                            x: r.x, y: r.y, width: r.width, height: r.height,
                            currently_following: isFollowing,
                            button_text: text
                        };
                    }
                }
                return null;
            })();
        """)

        if not btn_info:
            print("[cdp_publish] Could not find follow button.")
            return {"user_id": user_id, "success": False, "action": "button_not_found"}

        if btn_info.get("currently_following"):
            print(f"[cdp_publish] Already following (button: {btn_info.get('button_text', '')}).")
            return {"user_id": user_id, "success": True, "action": "already_following"}

        cx = btn_info["x"] + btn_info["width"] / 2
        cy = btn_info["y"] + btn_info["height"] / 2
        print(f"[cdp_publish] Clicking follow button at ({cx:.0f}, {cy:.0f})...")
        self._move_mouse(cx, cy)
        self._sleep(0.2, minimum_seconds=0.1)
        self._click_mouse(cx, cy)
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.5)

        print("[cdp_publish] User followed.")
        return {"user_id": user_id, "success": True, "action": "followed"}

    def unfollow_user(self, user_id: str) -> dict[str, Any]:
        """Unfollow a user via CDP mouse click.

        Args:
            user_id: Xiaohongshu user ID.

        Returns:
            {"user_id": "...", "success": True, "action": "unfollowed"|"not_following"}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        url = XHS_USER_PROFILE_URL_TEMPLATE.format(user_id=user_id.strip())
        print(f"[cdp_publish] Navigating to user profile for unfollow: {user_id}")
        self._navigate(url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=2.0)

        btn_info = self._evaluate("""
            (function() {
                var btns = document.querySelectorAll(
                    'button, [class*="follow-btn"], [class*="follow-button"], [role="button"]'
                );
                for (var i = 0; i < btns.length; i++) {
                    var el = btns[i];
                    if (!(el instanceof HTMLElement) || el.offsetParent === null) continue;
                    var text = (el.textContent || '').replace(/\\s+/g, '').trim();
                    var r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 15) continue;
                    var isFollowing = ['已关注', '互相关注', 'Following', 'Mutual'].some(function(k) {
                        return text.indexOf(k) >= 0;
                    });
                    if (isFollowing) {
                        return {
                            x: r.x, y: r.y, width: r.width, height: r.height,
                            currently_following: true,
                            button_text: text
                        };
                    }
                }
                return null;
            })();
        """)

        if not btn_info:
            print("[cdp_publish] Not following this user (no following button found).")
            return {"user_id": user_id, "success": True, "action": "not_following"}

        cx = btn_info["x"] + btn_info["width"] / 2
        cy = btn_info["y"] + btn_info["height"] / 2
        print(f"[cdp_publish] Clicking unfollow button at ({cx:.0f}, {cy:.0f})...")
        self._move_mouse(cx, cy)
        self._sleep(0.2, minimum_seconds=0.1)
        self._click_mouse(cx, cy)
        self._sleep(0.5, minimum_seconds=0.3)

        # Handle confirmation dialog if it appears
        self._evaluate("""
            (function() {
                var confirmBtns = document.querySelectorAll(
                    'button, [role="button"], [class*="confirm"], [class*="sure"]'
                );
                for (var i = 0; i < confirmBtns.length; i++) {
                    var text = (confirmBtns[i].textContent || '').trim();
                    if (text === '确认' || text === '确定' || text === '取消关注') {
                        confirmBtns[i].click();
                        return true;
                    }
                }
                return false;
            })();
        """)
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.5)

        print("[cdp_publish] User unfollowed.")
        return {"user_id": user_id, "success": True, "action": "unfollowed"}

    # ------------------------------------------------------------------
    # Autonomous browsing (AI agent mode)
    # ------------------------------------------------------------------

    def autonomous_browse(
        self,
        duration_minutes: int = 10,
        max_detail_reads: int = 8,
        like_interesting: bool = True,
        collect_interesting: bool = True,
    ) -> dict[str, Any]:
        """Autonomously browse Xiaohongshu for a given duration.

        Browses the home feed, reads interesting notes in detail,
        optionally likes/collects them, and returns a structured report.

        Note: The "interesting" judgment is NOT done here — this method
        reads notes and returns all data. Claude (via SKILL.md) decides
        which notes are interesting based on the persona's interests.

        Args:
            duration_minutes: How long to browse (approximate).
            max_detail_reads: Max notes to read in detail.
            like_interesting: Whether likes are enabled.
            collect_interesting: Whether collects are enabled.

        Returns:
            {"duration_minutes": N, "home_feeds": [...], "following_feeds": [...],
             "detail_reads": [...], "actions_taken": [...]}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        import time as _time
        start = _time.time()
        budget = duration_minutes * 60
        actions_taken = []
        detail_reads = []

        def time_left():
            return budget - (_time.time() - start)

        # Phase 1: Browse home feed (use ~40% of time)
        print(f"[cdp_publish] Autonomous browse: starting ({duration_minutes} min)...")
        home_result = self.browse_home_feed(
            max_items=30,
            scroll_count=min(5, max(2, duration_minutes // 2)),
        )
        home_feeds = home_result.get("feeds", [])

        # Phase 2: Read interesting notes in detail (use ~40% of time)
        reads_done = 0
        for feed in home_feeds:
            if reads_done >= max_detail_reads or time_left() < 30:
                break
            note_id = feed.get("note_id", "")
            xsec_token = feed.get("xsec_token", "")
            if not note_id or not xsec_token:
                continue

            try:
                detail = self.read_note_detail(
                    feed_id=note_id, xsec_token=xsec_token
                )
                detail_reads.append(detail)
                reads_done += 1

                # Brief pause between reads
                self._sleep(1.5, minimum_seconds=0.8)
            except Exception as e:
                print(f"[cdp_publish] Skipping note {note_id}: {e}")
                continue

        # Phase 3: Browse following feed (use ~20% of time)
        following_feeds = []
        if time_left() > 20:
            follow_result = self.browse_following_feed(
                max_items=20,
                scroll_count=min(3, max(1, duration_minutes // 4)),
            )
            following_feeds = follow_result.get("feeds", [])

        elapsed = (_time.time() - start) / 60
        print(
            f"[cdp_publish] Autonomous browse complete: "
            f"{elapsed:.1f} min, {len(home_feeds)} home feeds, "
            f"{reads_done} detail reads, {len(following_feeds)} following feeds."
        )

        return {
            "duration_minutes": round(elapsed, 1),
            "home_feed_count": len(home_feeds),
            "home_feeds": home_feeds,
            "following_feed_count": len(following_feeds),
            "following_feeds": following_feeds,
            "detail_reads_count": len(detail_reads),
            "detail_reads": detail_reads,
            "actions_taken": actions_taken,
            "like_enabled": like_interesting,
            "collect_enabled": collect_interesting,
        }

    def _select_collection_folder(self, folder_name: str) -> bool:
        """Try to select a specific collection folder after clicking collect.

        When XHS web shows a folder selection popup after collecting a note,
        try to find and click the target folder. If the popup doesn't appear
        or the folder isn't found, returns False (note is still collected
        to default folder).

        Args:
            folder_name: Name of the collection folder to select.

        Returns:
            True if folder was selected, False if not available.
        """
        self._sleep(0.8, minimum_seconds=0.4)

        safe_name = folder_name.replace("'", "\\'")
        result = self._evaluate(f"""
            (function() {{
                // Look for collection folder popup/dialog
                var popups = document.querySelectorAll(
                    '[class*="collect-popup"], [class*="folder"], [class*="board"],
                     [class*="collection-list"], [class*="save-to"]'
                );
                if (popups.length === 0) return {{ found: false, reason: 'no_popup' }};

                // Try to find the target folder
                var folderName = '{safe_name}';
                var allItems = document.querySelectorAll(
                    '[class*="folder-item"], [class*="board-item"],
                     [class*="collection-item"], li, [role="option"]'
                );
                for (var i = 0; i < allItems.length; i++) {{
                    var text = (allItems[i].textContent || '').trim();
                    if (text.indexOf(folderName) >= 0) {{
                        allItems[i].click();
                        return {{ found: true, selected: text }};
                    }}
                }}

                // Folder not found — try "新建收藏夹" / "Create" button
                var createBtns = document.querySelectorAll(
                    '[class*="create"], [class*="new-folder"], [class*="add-board"]'
                );
                for (var i = 0; i < createBtns.length; i++) {{
                    var text = (createBtns[i].textContent || '').trim();
                    if (text.indexOf('新建') >= 0 || text.indexOf('创建') >= 0) {{
                        return {{ found: false, reason: 'needs_create', create_button_text: text }};
                    }}
                }}

                return {{ found: false, reason: 'folder_not_found' }};
            }})();
        """)

        if result and result.get("found"):
            print(f"[cdp_publish] Selected folder: {result.get('selected')}")
            return True
        else:
            reason = result.get("reason", "unknown") if result else "no_popup"
            print(f"[cdp_publish] Could not select folder: {reason}")
            return False

    # ------------------------------------------------------------------
    # Reply to comments (nested/threaded replies)
    # ------------------------------------------------------------------

    def reply_to_comment(
        self,
        feed_id: str,
        xsec_token: str,
        comment_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Reply to a specific comment on a note (二级评论).

        Args:
            feed_id: Note/feed ID.
            xsec_token: Security token.
            comment_id: ID of the comment to reply to.
            content: Reply text.

        Returns:
            {"feed_id": "...", "comment_id": "...", "success": True/False,
             "action": "replied"/"failed"}
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        detail_url = make_feed_detail_url(feed_id, xsec_token)
        print(f"[cdp_publish] Navigating to note for comment reply: {feed_id}")
        self._navigate(detail_url)
        self._sleep(PAGE_LOAD_WAIT, minimum_seconds=2.0)

        self._check_feed_page_accessible()

        # Find the target comment and its reply button
        found = self._evaluate(f"""
            (function() {{
                // Try to find comment by ID attribute or data attribute
                var commentId = '{comment_id}';
                var commentEls = document.querySelectorAll(
                    '[class*="comment-item"], [class*="comment-inner"], [class*="note-comment"]'
                );
                for (var i = 0; i < commentEls.length; i++) {{
                    var el = commentEls[i];
                    // Check data attributes for comment ID
                    var dataId = el.getAttribute('data-id') ||
                                 el.getAttribute('data-comment-id') || '';
                    // Also check if inner content contains partial ID match
                    var idMatch = dataId === commentId;

                    if (!idMatch) {{
                        // Try matching by index if commentId looks like a number
                        var idx = parseInt(commentId, 10);
                        if (!isNaN(idx) && i === idx) idMatch = true;
                    }}

                    if (idMatch) {{
                        // Find reply button within or near this comment
                        var replyBtn = el.querySelector(
                            '[class*="reply"], [class*="回复"], button'
                        );
                        if (!replyBtn) {{
                            // Look for text-based reply links
                            var links = el.querySelectorAll('span, a, div');
                            for (var j = 0; j < links.length; j++) {{
                                var t = (links[j].textContent || '').trim();
                                if (t === '回复' || t === 'Reply') {{
                                    replyBtn = links[j];
                                    break;
                                }}
                            }}
                        }}
                        if (replyBtn) {{
                            var r = replyBtn.getBoundingClientRect();
                            return {{
                                found: true,
                                x: r.x, y: r.y,
                                width: r.width, height: r.height
                            }};
                        }}
                        return {{ found: false, reason: 'no_reply_button' }};
                    }}
                }}
                return {{ found: false, reason: 'comment_not_found' }};
            }})();
        """)

        if not found or not found.get("found"):
            reason = found.get("reason", "unknown") if found else "unknown"
            print(f"[cdp_publish] Could not find comment to reply: {reason}")
            return {
                "feed_id": feed_id,
                "comment_id": comment_id,
                "success": False,
                "action": "failed",
                "reason": reason,
            }

        # Click the reply button
        cx = found["x"] + found["width"] / 2
        cy = found["y"] + found["height"] / 2
        print(f"[cdp_publish] Clicking reply button at ({cx:.0f}, {cy:.0f})...")
        self._move_mouse(cx, cy)
        self._sleep(0.2, minimum_seconds=0.1)
        self._click_mouse(cx, cy)
        self._sleep(1.0, minimum_seconds=0.5)

        # Fill in the reply content using existing comment fill logic
        self._fill_comment_content(content)
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.5)

        print("[cdp_publish] Comment reply submitted.")
        return {
            "feed_id": feed_id,
            "comment_id": comment_id,
            "success": True,
            "action": "replied",
            "content": content,
        }

    def _click_publish(self):
        """Click the publish button using CDP mouse events."""
        print("[cdp_publish] Clicking publish button...")
        self._sleep(ACTION_INTERVAL, minimum_seconds=0.25)

        btn_text = SELECTORS["publish_button_text"]

        # JavaScript to locate the publish button and return its bounding rect
        js_get_rect = f"""
            (function() {{
                // Strategy 1: search <button> elements by exact text
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {{
                    var t = buttons[i].textContent.trim();
                    if (t === '{btn_text}') {{
                        var r = buttons[i].getBoundingClientRect();
                        return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
                    }}
                }}
                // Strategy 2: search d-button-content / d-text spans
                var spans = document.querySelectorAll(
                    '.d-button-content .d-text, .d-button-content span'
                );
                for (var i = 0; i < spans.length; i++) {{
                    if (spans[i].textContent.trim() === '{btn_text}') {{
                        var el = spans[i].closest(
                            'button, [role="button"], .d-button, [class*="btn"], [class*="button"]'
                        );
                        if (!el) el = spans[i];
                        var r = el.getBoundingClientRect();
                        return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
                    }}
                }}
                return null;
            }})();
        """

        self._click_element_by_cdp("publish button", js_get_rect)
        print("[cdp_publish] Publish button clicked.")

        # Wait for publish success and get note link
        self._sleep(5, minimum_seconds=2.0)
        note_link = self._evaluate("""
            (function() {
                // Try to find note link in success message
                var links = document.querySelectorAll('a[href*="xiaohongshu.com/explore"]');
                if (links.length > 0) {
                    return links[0].href;
                }
                // Try to find note ID in page
                var noteId = document.body.textContent.match(/\\b[0-9a-fA-F]{24}\\b/);
                if (noteId) {
                    return 'https://www.xiaohongshu.com/explore/' + noteId[0];
                }
                return null;
            })();
        """)

        return note_link

    # ------------------------------------------------------------------
    # Main publish workflow
    # ------------------------------------------------------------------

    def publish(
        self,
        title: str,
        content: str,
        image_paths: list[str] | None = None,
    ):
        """
        Execute the full publish workflow:
        1. Navigate to creator publish page
        2. Click '上传图文' tab
        3. Upload images (this triggers the editor to appear)
        4. Fill title
        5. Fill content

        Args:
            title: Article title
            content: Article body text (paragraphs separated by newlines)
            image_paths: List of local file paths to images to upload
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        if not image_paths:
            raise CDPError("At least one image is required to publish on Xiaohongshu.")

        # Step 1: Navigate to publish page
        self._navigate(XHS_CREATOR_URL)
        self._sleep(2, minimum_seconds=1.0)

        # Step 2: Click '上传图文' tab
        self._click_image_text_tab()

        # Step 3: Upload images (editor appears after upload)
        self._upload_images(image_paths)

        # Step 4: Fill title
        self._fill_title(title)

        # Step 5: Fill content
        self._fill_content(content)

        print(
            "\n[cdp_publish] Content has been filled in.\n"
            "  Please review in the browser before publishing.\n"
        )

    def publish_video(
        self,
        title: str,
        content: str,
        video_path: str,
    ):
        """
        Execute the full video publish workflow:
        1. Navigate to creator publish page
        2. Click '上传视频' tab
        3. Upload video file and wait for processing
        4. Fill title
        5. Fill content

        Args:
            title: Article title
            content: Article body text (paragraphs separated by newlines)
            video_path: Local file path to the video to upload
        """
        if not self.ws:
            raise CDPError("Not connected. Call connect() first.")

        if not video_path:
            raise CDPError("A video file is required to publish video on Xiaohongshu.")

        # Step 1: Navigate to publish page
        self._navigate(XHS_CREATOR_URL)
        time.sleep(2)

        # Step 2: Click '上传视频' tab
        self._click_video_tab()

        # Step 3: Upload video and wait for processing
        self._upload_video(video_path)
        self._wait_video_processing()

        # Step 4: Fill title
        self._fill_title(title)

        # Step 5: Fill content
        self._fill_content(content)

        print(
            "\n[cdp_publish] Video content has been filled in.\n"
            "  Please review in the browser before publishing.\n"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    from chrome_launcher import ensure_chrome, restart_chrome

    parser = argparse.ArgumentParser(description="Xiaohongshu CDP Publisher")
    parser.add_argument(
        "--host",
        default=CDP_HOST,
        help=f"CDP host (default: {CDP_HOST})",
    )
    parser.add_argument("--port", type=int, default=CDP_PORT,
                        help=f"CDP remote debugging port (default: {CDP_PORT})")
    parser.add_argument("--headless", action="store_true",
                        help="Use headless Chrome (no GUI window)")
    parser.add_argument("--account", help="Account name to use (default: default account)")
    parser.add_argument(
        "--timing-jitter",
        type=float,
        default=0.25,
        help=(
            "Timing jitter ratio for operation delays (default: 0.25). "
            "Set 0 to disable random jitter."
        ),
    )
    parser.add_argument(
        "--reuse-existing-tab",
        action="store_true",
        help=(
            "Prefer reusing an existing tab before creating a new one. "
            "Useful in headed mode to reduce foreground focus switching."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # check-login
    sub.add_parser("check-login", help="Check login status (exit 0=logged in, 1=not)")

    # fill - fill form without clicking publish
    p_fill = sub.add_parser("fill", help="Fill title/content/images or video without publishing")
    p_fill.add_argument("--title", required=True)
    p_fill.add_argument("--content", default=None)
    p_fill.add_argument("--content-file", default=None, help="Read content from file")
    p_fill_media = p_fill.add_mutually_exclusive_group(required=True)
    p_fill_media.add_argument("--images", nargs="+", help="Local image file paths")
    p_fill_media.add_argument("--video", help="Local video file path")

    # publish - fill form and click publish
    p_pub = sub.add_parser("publish", help="Fill form and click publish")
    p_pub.add_argument("--title", required=True)
    p_pub.add_argument("--content", default=None)
    p_pub.add_argument("--content-file", default=None, help="Read content from file")
    p_pub_media = p_pub.add_mutually_exclusive_group(required=True)
    p_pub_media.add_argument("--images", nargs="+", help="Local image file paths")
    p_pub_media.add_argument("--video", help="Local video file path")

    # click-publish - just click the publish button on current page
    sub.add_parser("click-publish", help="Click publish button on already-filled page")

    # search-feeds - search note feeds by keyword
    p_search = sub.add_parser(
        "search-feeds",
        aliases=["search_feeds"],
        help="Search Xiaohongshu feeds by keyword",
    )
    p_search.add_argument("--keyword", required=True, help="Search keyword")
    p_search.add_argument("--sort-by", choices=SORT_BY_OPTIONS, help="Sort by option")
    p_search.add_argument("--note-type", choices=NOTE_TYPE_OPTIONS, help="Note type filter")
    p_search.add_argument(
        "--publish-time",
        choices=PUBLISH_TIME_OPTIONS,
        help="Publish time filter",
    )
    p_search.add_argument(
        "--search-scope",
        choices=SEARCH_SCOPE_OPTIONS,
        help="Search scope filter",
    )
    p_search.add_argument("--location", choices=LOCATION_OPTIONS, help="Location filter")

    # get-feed-detail - get note detail by feed id and token
    p_detail = sub.add_parser(
        "get-feed-detail",
        aliases=["get_feed_detail"],
        help="Get feed detail by feed id and xsec token",
    )
    p_detail.add_argument("--feed-id", required=True, help="Feed id")
    p_detail.add_argument("--xsec-token", required=True, help="xsec token")

    # post-comment-to-feed - post top-level comment to feed detail
    p_comment = sub.add_parser(
        "post-comment-to-feed",
        aliases=["post_comment_to_feed"],
        help="Post a top-level comment to feed detail",
    )
    p_comment.add_argument("--feed-id", required=True, help="Feed id")
    p_comment.add_argument("--xsec-token", required=True, help="xsec token")
    p_comment_content = p_comment.add_mutually_exclusive_group(required=True)
    p_comment_content.add_argument("--content", help="Comment content")
    p_comment_content.add_argument("--content-file", help="Read comment content from file")

    # get-notification-mentions - capture notification mentions API response
    p_mentions = sub.add_parser(
        "get-notification-mentions",
        aliases=["get_notification_mentions"],
        help="Capture notification mentions API payload from /notification page",
    )
    p_mentions.add_argument(
        "--wait-seconds",
        type=float,
        default=18.0,
        help="Max seconds to wait for mentions API request (default: 18)",
    )

    # content-data - fetch creator content data table
    p_content_data = sub.add_parser(
        "content-data",
        aliases=["content_data"],
        help="Fetch creator content data table from statistics page",
    )
    p_content_data.add_argument(
        "--page-num",
        type=int,
        default=1,
        help="Page number (default: 1)",
    )
    p_content_data.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Page size (default: 10)",
    )
    p_content_data.add_argument(
        "--type",
        dest="note_type",
        type=int,
        default=0,
        help="Type filter value used by API (default: 0)",
    )
    p_content_data.add_argument(
        "--csv-file",
        help="Optional CSV output path",
    )

    # login - open browser for QR code login (always headed)
    sub.add_parser("login", help="Open browser for QR code login (always headed mode)")

    # re-login - clear cookies and re-login the same account (always headed)
    sub.add_parser("re-login", help="Clear cookies and re-login same account (always headed)")

    # switch-account - clear cookies and open login page (always headed)
    sub.add_parser("switch-account",
                   help="Clear cookies and open login page for new account (always headed)")

    # list-accounts - list all configured accounts
    sub.add_parser("list-accounts", help="List all configured accounts")

    # add-account - add a new account
    p_add = sub.add_parser("add-account", help="Add a new account")
    p_add.add_argument("name", help="Account name (unique identifier)")
    p_add.add_argument("--alias", help="Display name / description")

    # remove-account - remove an account
    p_rm = sub.add_parser("remove-account", help="Remove an account")
    p_rm.add_argument("name", help="Account name to remove")
    p_rm.add_argument("--delete-profile", action="store_true",
                      help="Also delete the Chrome profile directory")

    # set-default-account - set default account
    p_def = sub.add_parser("set-default-account", help="Set the default account")
    p_def.add_argument("name", help="Account name to set as default")

    # ---- Browsing & interaction commands ----

    # browse-home-feed
    p_home = sub.add_parser(
        "browse-home-feed",
        aliases=["browse_home_feed"],
        help="Browse Xiaohongshu explore/home feed",
    )
    p_home.add_argument("--max-items", type=int, default=20, help="Max items (default: 20)")
    p_home.add_argument("--scroll-count", type=int, default=3, help="Scroll iterations (default: 3)")
    p_home.add_argument("--screenshot", action="store_true", help="Take screenshot after loading")

    # browse-following-feed
    p_follow_feed = sub.add_parser(
        "browse-following-feed",
        aliases=["browse_following_feed"],
        help="Browse content from followed users",
    )
    p_follow_feed.add_argument("--max-items", type=int, default=20, help="Max items (default: 20)")
    p_follow_feed.add_argument("--scroll-count", type=int, default=3, help="Scroll iterations (default: 3)")
    p_follow_feed.add_argument("--screenshot", action="store_true", help="Take screenshot")

    # read-note-detail
    p_read = sub.add_parser(
        "read-note-detail",
        aliases=["read_note_detail"],
        help="Read full note content, images, and comments",
    )
    p_read.add_argument("--feed-id", required=True, help="Feed id")
    p_read.add_argument("--xsec-token", required=True, help="xsec token")
    p_read.add_argument("--screenshot", action="store_true", help="Take screenshot")

    # like-note
    p_like = sub.add_parser(
        "like-note",
        aliases=["like_note"],
        help="Like a note",
    )
    p_like.add_argument("--feed-id", required=True, help="Feed id")
    p_like.add_argument("--xsec-token", required=True, help="xsec token")

    # collect-note
    p_collect = sub.add_parser(
        "collect-note",
        aliases=["collect_note", "bookmark-note", "bookmark_note"],
        help="Collect/bookmark a note",
    )
    p_collect.add_argument("--feed-id", required=True, help="Feed id")
    p_collect.add_argument("--xsec-token", required=True, help="xsec token")

    # view-user-profile
    p_profile = sub.add_parser(
        "view-user-profile",
        aliases=["view_user_profile"],
        help="View a user's profile and notes list",
    )
    p_profile.add_argument("--user-id", required=True, help="User ID")
    p_profile.add_argument("--max-notes", type=int, default=20, help="Max notes (default: 20)")
    p_profile.add_argument("--scroll-count", type=int, default=2, help="Scroll iterations (default: 2)")
    p_profile.add_argument("--screenshot", action="store_true", help="Take screenshot")

    # follow-user
    p_fu = sub.add_parser(
        "follow-user",
        aliases=["follow_user"],
        help="Follow a user",
    )
    p_fu.add_argument("--user-id", required=True, help="User ID")

    # unfollow-user
    p_ufu = sub.add_parser(
        "unfollow-user",
        aliases=["unfollow_user"],
        help="Unfollow a user",
    )
    p_ufu.add_argument("--user-id", required=True, help="User ID")

    # capture-screenshot
    p_ss = sub.add_parser(
        "capture-screenshot",
        aliases=["capture_screenshot", "screenshot"],
        help="Capture a screenshot of the current page",
    )
    p_ss.add_argument("--output", help="Output file path")
    p_ss.add_argument("--quality", type=int, default=80, help="JPEG quality (default: 80)")

    # scroll-page
    p_scroll = sub.add_parser(
        "scroll-page",
        aliases=["scroll_page"],
        help="Scroll the current page",
    )
    p_scroll.add_argument("--direction", choices=["up", "down"], default="down", help="Direction")
    p_scroll.add_argument("--distance", type=int, default=600, help="Pixels (default: 600)")

    # autonomous-browse
    p_auto = sub.add_parser(
        "autonomous-browse",
        aliases=["autonomous_browse"],
        help="Autonomously browse XHS and return a report",
    )
    p_auto.add_argument(
        "--duration", type=int, default=10,
        help="Browse duration in minutes (default: 10)"
    )
    p_auto.add_argument(
        "--max-detail-reads", type=int, default=8,
        help="Max notes to read in detail (default: 8)"
    )

    # reply-to-comment
    p_reply = sub.add_parser(
        "reply-to-comment",
        aliases=["reply_to_comment"],
        help="Reply to a specific comment on a note",
    )
    p_reply.add_argument("--feed-id", required=True, help="Feed id")
    p_reply.add_argument("--xsec-token", required=True, help="xsec token")
    p_reply.add_argument("--comment-id", required=True, help="Comment ID or index")
    p_reply_content = p_reply.add_mutually_exclusive_group(required=True)
    p_reply_content.add_argument("--content", help="Reply content")
    p_reply_content.add_argument("--content-file", help="Read reply content from file")

    # get-persona
    p_persona = sub.add_parser(
        "get-persona",
        aliases=["get_persona"],
        help="Show current persona configuration",
    )

    args = parser.parse_args()
    host = args.host
    port = args.port
    headless = args.headless
    account = args.account
    cache_account_name = _resolve_account_name(account)
    reuse_existing_tab = args.reuse_existing_tab
    timing_jitter = _normalize_timing_jitter(args.timing_jitter)
    local_mode = _is_local_host(host)

    if timing_jitter != args.timing_jitter:
        print(
            "[cdp_publish] Warning: --timing-jitter out of range. "
            f"Clamped to {timing_jitter:.2f}."
        )
    # Account management commands that don't need Chrome
    if args.command == "list-accounts":
        from account_manager import list_accounts
        accounts = list_accounts()
        if not accounts:
            print("No accounts configured.")
            return
        print(f"{'Name':<20} {'Alias':<25} {'Default':<10}")
        print("-" * 55)
        for acc in accounts:
            default_mark = "*" if acc["is_default"] else ""
            print(f"{acc['name']:<20} {acc['alias']:<25} {default_mark:<10}")
        return

    elif args.command == "add-account":
        from account_manager import add_account, get_profile_dir
        if add_account(args.name, args.alias):
            print(f"Account '{args.name}' added.")
            print(f"Profile dir: {get_profile_dir(args.name)}")
            print("\nTo log in to this account, run:")
            print(f"  python cdp_publish.py --account {args.name} login")
        else:
            print(f"Error: Account '{args.name}' already exists.", file=sys.stderr)
            sys.exit(1)
        return

    elif args.command == "remove-account":
        from account_manager import remove_account
        if remove_account(args.name, args.delete_profile):
            print(f"Account '{args.name}' removed.")
        else:
            print(f"Error: Cannot remove account '{args.name}'.", file=sys.stderr)
            sys.exit(1)
        return

    elif args.command == "set-default-account":
        from account_manager import set_default_account
        if set_default_account(args.name):
            print(f"Default account set to '{args.name}'.")
        else:
            print(f"Error: Account '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        return

    # Commands that require Chrome - login/re-login/switch-account always headed
    if args.command in ("login", "re-login", "switch-account"):
        headless = False

    if local_mode:
        if not ensure_chrome(port=port, headless=headless, account=account):
            print("Failed to start Chrome. Exiting.")
            sys.exit(1)
    else:
        print(
            f"[cdp_publish] Remote CDP mode enabled: {host}:{port}. "
            "Skipping local Chrome launch/restart."
        )

    print(f"[cdp_publish] Timing jitter ratio: {timing_jitter:.2f}")
    print(f"[cdp_publish] Login cache: enabled (ttl={DEFAULT_LOGIN_CACHE_TTL_HOURS:g}h).")
    if reuse_existing_tab:
        print("[cdp_publish] Tab selection mode: prefer reusing existing tab.")

    publisher = XiaohongshuPublisher(
        host=host,
        port=port,
        timing_jitter=timing_jitter,
        account_name=cache_account_name,
    )
    try:
        if args.command == "check-login":
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            logged_in = publisher.check_login()
            if not logged_in and headless:
                print(
                    "[cdp_publish] Headless mode: cannot scan QR code.\n"
                    "  Run with 'login' command or without --headless to log in."
                )
            sys.exit(0 if logged_in else 1)

        elif args.command in ("fill", "publish"):
            content = args.content
            if args.content_file:
                with open(args.content_file, encoding="utf-8") as f:
                    content = f.read().strip()
            if not content:
                print("Error: --content or --content-file required.", file=sys.stderr)
                sys.exit(1)

            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if getattr(args, "video", None):
                publisher.publish_video(
                    title=args.title, content=content, video_path=args.video
                )
            else:
                publisher.publish(
                    title=args.title, content=content, image_paths=args.images
                )
            print("FILL_STATUS: READY_TO_PUBLISH")

            if args.command == "publish":
                publisher._click_publish()
                print("PUBLISH_STATUS: PUBLISHED")

        elif args.command == "click-publish":
            publisher.connect(
                target_url_prefix="https://creator.xiaohongshu.com/publish",
                reuse_existing_tab=reuse_existing_tab,
            )
            publisher._click_publish()
            print("PUBLISH_STATUS: PUBLISHED")

        elif args.command in ("search-feeds", "search_feeds"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)

            filters = _build_search_filters_from_args(args)
            search_result = publisher.search_feeds(keyword=args.keyword, filters=filters)
            feeds = search_result.get("feeds", [])
            recommended_keywords = search_result.get("recommended_keywords", [])
            payload = {
                "keyword": args.keyword,
                "recommended_keywords_count": len(recommended_keywords),
                "recommended_keywords": recommended_keywords,
                "count": len(feeds),
                "feeds": feeds,
            }
            print("SEARCH_FEEDS_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("get-feed-detail", "get_feed_detail"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)

            detail = publisher.get_feed_detail(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
            )
            payload = {
                "feed_id": args.feed_id,
                "xsec_token": args.xsec_token,
                "detail": detail,
            }
            print("GET_FEED_DETAIL_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("post-comment-to-feed", "post_comment_to_feed"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)

            comment_content = args.content
            if args.content_file:
                with open(args.content_file, encoding="utf-8") as f:
                    comment_content = f.read().strip()
            if not comment_content:
                print("Error: --content or --content-file required.", file=sys.stderr)
                sys.exit(1)

            payload = publisher.post_comment_to_feed(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
                content=comment_content,
            )
            print("POST_COMMENT_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("get-notification-mentions", "get_notification_mentions"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)

            payload = publisher.get_notification_mentions(wait_seconds=args.wait_seconds)
            print("GET_NOTIFICATION_MENTIONS_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("content-data", "content_data"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)

            payload = publisher.get_content_data(
                page_num=args.page_num,
                page_size=args.page_size,
                note_type=args.note_type,
            )
            print("CONTENT_DATA_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

            if args.csv_file:
                csv_path = _write_content_data_csv(
                    csv_file=args.csv_file,
                    rows=payload.get("rows", []),
                )
                print(f"CONTENT_DATA_CSV: {csv_path}")

        elif args.command == "login":
            # Ensure headed mode for QR scanning
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.open_login_page()
            print("LOGIN_READY")

        elif args.command == "re-login":
            # Ensure headed mode, clear cookies, re-open login page for same account
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.clear_cookies()
            publisher._sleep(1, minimum_seconds=0.5)
            publisher.open_login_page()
            print("RE_LOGIN_READY")

        elif args.command == "switch-account":
            # Ensure headed mode, clear cookies, open login page
            if local_mode:
                restart_chrome(port=port, headless=False, account=account)
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            publisher.clear_cookies()
            publisher._sleep(1, minimum_seconds=0.5)
            publisher.open_login_page()
            print("SWITCH_ACCOUNT_READY")

        # ---- Browsing & interaction command handlers ----

        elif args.command in ("browse-home-feed", "browse_home_feed"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.browse_home_feed(
                max_items=args.max_items,
                scroll_count=args.scroll_count,
                take_screenshot=args.screenshot,
            )
            print("BROWSE_HOME_FEED_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("browse-following-feed", "browse_following_feed"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.browse_following_feed(
                max_items=args.max_items,
                scroll_count=args.scroll_count,
                take_screenshot=args.screenshot,
            )
            print("BROWSE_FOLLOWING_FEED_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("read-note-detail", "read_note_detail"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.read_note_detail(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
                take_screenshot=args.screenshot,
            )
            print("READ_NOTE_DETAIL_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("like-note", "like_note"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.like_note(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
            )
            print("LIKE_NOTE_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("collect-note", "collect_note", "bookmark-note", "bookmark_note"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.collect_note(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
            )
            print("COLLECT_NOTE_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("view-user-profile", "view_user_profile"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.view_user_profile(
                user_id=args.user_id,
                max_notes=args.max_notes,
                scroll_count=args.scroll_count,
                take_screenshot=args.screenshot,
            )
            print("VIEW_USER_PROFILE_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("follow-user", "follow_user"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.follow_user(user_id=args.user_id)
            print("FOLLOW_USER_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("unfollow-user", "unfollow_user"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.unfollow_user(user_id=args.user_id)
            print("UNFOLLOW_USER_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("capture-screenshot", "capture_screenshot", "screenshot"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            payload = publisher.capture_screenshot(
                output_path=args.output,
                quality=args.quality,
            )
            print("CAPTURE_SCREENSHOT_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("scroll-page", "scroll_page"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            payload = publisher._scroll_page(
                direction=args.direction,
                distance=args.distance,
            )
            print("SCROLL_PAGE_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("autonomous-browse", "autonomous_browse"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            payload = publisher.autonomous_browse(
                duration_minutes=args.duration,
                max_detail_reads=args.max_detail_reads,
            )
            print("AUTONOMOUS_BROWSE_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("reply-to-comment", "reply_to_comment"):
            publisher.connect(reuse_existing_tab=reuse_existing_tab)
            if not publisher.check_home_login():
                print("NOT_LOGGED_IN")
                sys.exit(1)
            reply_content = args.content
            if args.content_file:
                with open(args.content_file, encoding="utf-8") as f:
                    reply_content = f.read().strip()
            if not reply_content:
                print("Error: --content or --content-file required.", file=sys.stderr)
                sys.exit(1)
            payload = publisher.reply_to_comment(
                feed_id=args.feed_id,
                xsec_token=args.xsec_token,
                comment_id=args.comment_id,
                content=reply_content,
            )
            print("REPLY_TO_COMMENT_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        elif args.command in ("get-persona", "get_persona"):
            from persona_manager import load_persona, get_prompt_prefix, is_initialized
            persona = load_persona()
            payload = {
                "initialized": is_initialized(),
                "persona": persona,
                "prompt_prefix": get_prompt_prefix(),
            }
            print("GET_PERSONA_RESULT:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    finally:
        publisher.disconnect()


if __name__ == "__main__":
    try:
        with single_instance("post_to_xhs_publish"):
            main()
    except SingleInstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)
