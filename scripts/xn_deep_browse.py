"""
小N 深度体验脚本 v2 — 确保帖子真的打开，截图内容，发评论。

v1问题：get_visible_cards 返回的卡片点击后没打开详情弹窗。
v2改进：点击后检测是否真的出现了详情弹窗（检查关闭按钮×或评论区），没打开就重试。

两种模式：
- browse: 只浏览截图，不评论
- comment: 带评论JSON文件，浏览+评论
"""
from __future__ import annotations
import time, json, os, random, sys, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from xn_browse import (
    human_click, human_mouse_move, human_pause, human_scroll,
    screenshot, get_visible_cards, card_center, SS_DIR, USER_DATA
)
import xn_browse

SS_MAP_DIR = os.path.join(SS_DIR, "deep_browse")
os.makedirs(SS_MAP_DIR, exist_ok=True)

step_counter = 0

def ss(page, name):
    global step_counter
    step_counter += 1
    fname = f"{step_counter:02d}_{name}"
    path = os.path.join(SS_MAP_DIR, fname)
    page.screenshot(path=path)
    print(f"  [截图] {fname}")
    return path


def is_detail_open(page):
    """Check if a note detail overlay is open by looking for the close button or engage bar."""
    return page.evaluate("""() => {
        // Check for close button (× in top-left)
        const closeBtn = document.querySelector('.close-circle, [class*="close"], .note-detail-mask');
        // Check for engage bar (only in detail view)
        const engageBar = document.querySelector('.interactions.engage-bar, .engage-bar-container');
        // Check for note detail container
        const noteDetail = document.querySelector('.note-detail-mask, [class*="note-detail"]');
        return !!(closeBtn || engageBar || noteDetail);
    }""")


def click_card_reliably(page, card, last_mouse):
    """Click a card and verify the detail opened. Return (last_mouse, success)."""
    cx, cy = card_center(card)

    # Try clicking the card
    last_mouse = human_click(page, cx, cy, *last_mouse)
    time.sleep(2.0)

    if is_detail_open(page):
        return last_mouse, True

    # Retry: click more toward center of the card image (upper part)
    cx2 = card["x"] + card["width"] / 2 + random.uniform(-5, 5)
    cy2 = card["y"] + card["height"] * 0.3 + random.uniform(-5, 5)  # Upper third
    last_mouse = human_click(page, cx2, cy2, *last_mouse)
    time.sleep(2.0)

    if is_detail_open(page):
        return last_mouse, True

    return last_mouse, False


def find_comment_input(page):
    """用JS找评论输入框"""
    return page.evaluate("""() => {
        const editables = document.querySelectorAll('[contenteditable="true"]');
        let best = null;
        for (const el of editables) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 30 && rect.height > 10 && rect.y > 300) {
                const candidate = {
                    x: rect.x, y: rect.y, w: rect.width, h: rect.height
                };
                if (!best || rect.y > best.y) best = candidate;
            }
        }
        return best;
    }""")


def find_send_button(page):
    """找发送按钮"""
    return page.evaluate("""() => {
        const allEls = document.querySelectorAll('button, span, div, a');
        for (const el of allEls) {
            const text = (el.textContent || '').trim();
            if (text === '发送') {
                const rect = el.getBoundingClientRect();
                if (rect.width > 15 && rect.height > 15 && rect.y > 300) {
                    return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
                }
            }
        }
        return null;
    }""")


def post_comment(page, comment_text, last_mouse):
    """发送评论"""
    for attempt in range(3):
        input_box = find_comment_input(page)
        if input_box:
            break
        time.sleep(1.5)

    if not input_box:
        print("  [找不到评论输入框]")
        return last_mouse, False

    # Click input
    cx = input_box['x'] + input_box['w'] / 2
    cy = input_box['y'] + input_box['h'] / 2
    last_mouse = human_click(page, cx, cy, *last_mouse)
    time.sleep(1.0)

    # Re-find after expansion
    expanded = find_comment_input(page)
    if expanded and expanded['w'] > input_box['w'] + 50:
        ex = expanded['x'] + expanded['w'] / 2
        ey = expanded['y'] + expanded['h'] / 2
        last_mouse = human_click(page, ex, ey, *last_mouse)
        time.sleep(0.5)

    # Type
    for ch in comment_text:
        page.keyboard.type(ch, delay=0)
        time.sleep(random.uniform(0.03, 0.08))
    time.sleep(0.5)

    # Send
    send_btn = find_send_button(page)
    if send_btn:
        bx = send_btn['x'] + send_btn['w'] / 2
        by = send_btn['y'] + send_btn['h'] / 2
        last_mouse = human_click(page, bx, by, *last_mouse)
    else:
        page.keyboard.press("Control+Enter")

    time.sleep(2.0)
    return last_mouse, True


def main():
    xn_browse.SPEED = 2.0

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-notes", type=int, default=5)
    parser.add_argument("--comment-file", default=None,
                        help="JSON file: {\"0\": \"comment for note 0\", ...}")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA,
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    last_mouse = (640, 450)

    comments = {}
    if args.comment_file and os.path.exists(args.comment_file):
        with open(args.comment_file, 'r', encoding='utf-8') as f:
            comments = json.load(f)

    notes_data = []

    try:
        print("[小N] 出发~")
        page.goto("https://www.xiaohongshu.com/explore",
                   wait_until="domcontentloaded", timeout=30000)
        human_pause("read")
        ss(page, "home.png")

        # Scroll to load
        for _ in range(2):
            human_scroll(page, "down")
            human_pause("glance")
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        human_pause("scroll")

        seen_indices = set()
        notes_opened = 0

        for round_num in range(20):
            if notes_opened >= args.max_notes:
                break

            visible = get_visible_cards(page)
            unseen = [c for c in visible if c["index"] not in seen_indices]

            if not unseen:
                human_scroll(page, "down", total_distance=500)
                human_pause("glance")
                continue

            card = unseen[0]
            seen_indices.add(card["index"])

            print(f"\n[小N] 第{notes_opened + 1}篇 — 点击卡片 index={card['index']}")

            last_mouse, opened = click_card_reliably(page, card, last_mouse)

            if not opened:
                print("  [打开失败，跳过]")
                continue

            print("  [详情已打开!]")
            nid = f"note{notes_opened}"

            # Screenshot content
            top_ss = ss(page, f"{nid}_content.png")

            # Scroll in the right panel to see more
            # Move mouse to right side first to ensure scroll targets the detail
            rx = 800 + random.uniform(-20, 20)
            ry = 400 + random.uniform(-20, 20)
            last_mouse = human_mouse_move(page, rx, ry, *last_mouse)
            human_scroll(page, "down", total_distance=400)
            human_pause("glance")
            mid_ss = ss(page, f"{nid}_more.png")

            # Scroll more for comments
            human_scroll(page, "down", total_distance=300)
            human_pause("glance")
            bot_ss = ss(page, f"{nid}_comments.png")

            notes_data.append({
                "index": notes_opened,
                "screenshots": [top_ss, mid_ss, bot_ss],
            })

            # Post comment if available
            comment_key = str(notes_opened)
            if comment_key in comments:
                comment_text = comments[comment_key]
                print(f"  [评论] {comment_text}")
                last_mouse, success = post_comment(page, comment_text, last_mouse)
                if success:
                    result_ss = ss(page, f"{nid}_commented.png")
                    print("  [评论成功!]")
                else:
                    print("  [评论失败]")

            notes_opened += 1

            # Close
            page.keyboard.press("Escape")
            time.sleep(0.5)
            # Check if still open (sometimes Escape hits the expanded input first)
            if is_detail_open(page):
                page.keyboard.press("Escape")
                time.sleep(0.5)
            human_pause("scroll")

            if notes_opened < args.max_notes:
                human_scroll(page, "down", total_distance=random.randint(300, 500))
                human_pause("glance")

        ss(page, "final.png")
        print(f"\n[小N] 看了 {notes_opened} 篇!")

    except Exception as e:
        print(f"[小N] 出错了: {e}")
        import traceback
        traceback.print_exc()
        ss(page, "error.png")
    finally:
        human_pause("glance")
        ctx.close()
        pw.stop()

    print("\n" + json.dumps({"notes": notes_data}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
