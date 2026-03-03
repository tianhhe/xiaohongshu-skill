"""
小N browsing session — browse Xiaohongshu like a real person.

Simulates genuine human behavior:
- Mouse moves along curved paths (bezier), not straight lines
- Scrolling speed varies — fast skimming, slow reading pauses
- Random micro-pauses, hesitations, speed changes
- Takes screenshots at each step so Claude can "see" visually
- Does NOT scrape/crawl DOM text — all reading is via screenshots
"""
from __future__ import annotations
import time, json, os, random, sys, argparse, math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
SS_DIR = os.path.join(PROJECT_DIR, "tmp", "screenshots")
USER_DATA = os.path.join(PROJECT_DIR, "playwright_data")
os.makedirs(SS_DIR, exist_ok=True)

# Global speed multiplier: higher = faster browsing (e.g. 2.0 = all waits halved)
SPEED = 1.0


# ────────────────────────────────────────
# Human-like timing
# ────────────────────────────────────────

def jitter(base: float, ratio: float = 0.4, minimum: float = 0.05) -> float:
    """Randomize a base duration. ratio=0.4 means ±40%."""
    delta = base * ratio
    lo = max(minimum, base - delta)
    hi = max(lo, base + delta)
    return random.uniform(lo, hi)


def human_pause(style: str = "glance"):
    """
    Pause like a human would in different reading contexts.
    All durations are divided by global SPEED multiplier.
    - glance:  quick look
    - read:    actually reading
    - think:   paused to think about it
    - scroll:  between scrolls
    """
    durations = {
        "glance": (0.3, 1.0),
        "read":   (1.0, 2.5),
        "think":  (1.5, 3.5),
        "scroll": (0.2, 0.8),
    }
    lo, hi = durations.get(style, (0.5, 1.5))
    lo /= SPEED
    hi /= SPEED
    time.sleep(random.uniform(lo, hi))


# ────────────────────────────────────────
# Human-like mouse movement (bezier curve)
# ────────────────────────────────────────

def _bezier_point(t, p0, p1, p2, p3):
    """Cubic bezier interpolation at parameter t."""
    u = 1 - t
    return (u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3)


def human_mouse_move(page, to_x, to_y, from_x=None, from_y=None):
    """
    Move mouse from current position to (to_x, to_y) along a curved path.
    Uses a cubic bezier with randomized control points for natural motion.
    Speed varies: starts slow, speeds up in the middle, slows at the end.
    """
    if from_x is None or from_y is None:
        # Start from a reasonable position (center-ish area)
        from_x = from_x or random.uniform(300, 900)
        from_y = from_y or random.uniform(200, 600)

    dx = to_x - from_x
    dy = to_y - from_y
    dist = math.sqrt(dx * dx + dy * dy)

    # Number of steps proportional to distance (more steps = smoother)
    steps = max(8, min(35, int(dist / 15)))

    # Two random control points for the bezier curve (adds natural arc)
    # Offset perpendicular to the line for a curved path
    perp_x = -dy / max(dist, 1)  # perpendicular direction
    perp_y = dx / max(dist, 1)
    curve_amount = random.uniform(-0.3, 0.3) * dist  # how much curve

    cp1_x = from_x + dx * 0.25 + perp_x * curve_amount * random.uniform(0.5, 1.5)
    cp1_y = from_y + dy * 0.25 + perp_y * curve_amount * random.uniform(0.5, 1.5)
    cp2_x = from_x + dx * 0.75 + perp_x * curve_amount * random.uniform(0.3, 0.8)
    cp2_y = from_y + dy * 0.75 + perp_y * curve_amount * random.uniform(0.3, 0.8)

    for i in range(steps + 1):
        t = i / steps
        # Ease-in-out: slow at start and end, fast in middle
        t_eased = t * t * (3 - 2 * t)

        x = _bezier_point(t_eased, from_x, cp1_x, cp2_x, to_x)
        y = _bezier_point(t_eased, from_y, cp1_y, cp2_y, to_y)

        page.mouse.move(x, y)

        # Variable delay: slower at start/end, faster in middle
        if t < 0.15 or t > 0.85:
            time.sleep(random.uniform(0.01, 0.03))  # slow at edges
        else:
            time.sleep(random.uniform(0.004, 0.015))  # fast in middle

        # Occasional micro-pause (human hand tremor / hesitation)
        if random.random() < 0.05:
            time.sleep(random.uniform(0.02, 0.08))

    return to_x, to_y


def human_click(page, x, y, from_x=None, from_y=None):
    """Move to target with natural mouse path, then click with realistic timing."""
    fx, fy = human_mouse_move(page, x, y, from_x, from_y)

    # Small delay before clicking (human reaction time)
    time.sleep(random.uniform(0.05, 0.15))

    # mousedown
    page.mouse.down()
    # Hold for a natural duration (humans don't click instantly)
    time.sleep(random.uniform(0.04, 0.12))
    # mouseup
    page.mouse.up()

    return fx, fy


# ────────────────────────────────────────
# Human-like scrolling
# ────────────────────────────────────────

def human_scroll(page, direction="down", total_distance=None):
    """
    Scroll like a real person: variable speed, sometimes fast, sometimes slow,
    with pauses in between as if reading something that caught the eye.
    """
    if total_distance is None:
        total_distance = random.randint(400, 800)

    sign = 1 if direction == "down" else -1

    # Break into 3-6 uneven chunks
    num_chunks = random.randint(3, 6)
    # Generate random weights, then scale to total distance
    weights = [random.uniform(0.3, 1.0) for _ in range(num_chunks)]
    total_weight = sum(weights)
    chunks = [int(total_distance * w / total_weight) for w in weights]

    for i, chunk in enumerate(chunks):
        # Sometimes do a quick flick, sometimes a gentle scroll
        if random.random() < 0.3:
            # Quick flick — one big scroll event
            page.mouse.wheel(0, chunk * sign)
            time.sleep(random.uniform(0.1, 0.3))
        else:
            # Gentle scroll — a few small steps
            micro_steps = random.randint(2, 4)
            micro_dist = chunk // micro_steps
            for _ in range(micro_steps):
                page.mouse.wheel(0, (micro_dist + random.randint(-10, 10)) * sign)
                time.sleep(random.uniform(0.03, 0.1))

        # Pause between chunks (simulates reading / looking)
        if random.random() < 0.4:
            # Longer pause — something caught the eye
            human_pause("glance")
        else:
            human_pause("scroll")

    # Final settle time
    time.sleep(random.uniform(0.5, 1.0))


# ────────────────────────────────────────
# Screenshot helper
# ────────────────────────────────────────

def screenshot(page, name):
    path = os.path.join(SS_DIR, name)
    page.screenshot(path=path)
    print(f"  [截图] {name}")
    return path


# ────────────────────────────────────────
# Page helpers
# ────────────────────────────────────────

def get_visible_cards(page):
    """Get bounding boxes of note cards currently visible in viewport."""
    return page.evaluate("""() => {
        const items = document.querySelectorAll('section.note-item');
        const result = [];
        for (let i = 0; i < items.length; i++) {
            const rect = items[i].getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0
                && rect.width > 50 && rect.height > 50) {
                result.push({
                    x: rect.x, y: rect.y,
                    width: rect.width, height: rect.height,
                    index: i
                });
            }
        }
        return result;
    }""")


def find_clickable(page, selectors):
    """Find the first visible & clickable element's bounding box from selector list."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                box = el.bounding_box()
                if box and box["width"] > 0 and box["height"] > 0:
                    # Must be within viewport
                    if 0 < box["y"] < 900 and 0 < box["x"] < 1280:
                        return box
        except Exception:
            continue
    return None


def card_center(box):
    """Get center of a card box with slight random offset (not pixel perfect)."""
    return (
        box["x"] + box["width"] / 2 + random.uniform(-8, 8),
        box["y"] + box["height"] / 2 + random.uniform(-8, 8),
    )


# ────────────────────────────────────────
# Main browsing session
# ────────────────────────────────────────

def main():
    global SPEED
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-notes", type=int, default=15)
    parser.add_argument("--folder-name", default="小N的收藏夹")
    parser.add_argument("--no-like", action="store_true")
    parser.add_argument("--no-collect", action="store_true")
    parser.add_argument("--speed", type=float, default=1.5,
                        help="Speed multiplier: 1.0=normal, 2.0=2x faster, 3.0=3x faster")
    args = parser.parse_args()
    SPEED = max(0.5, args.speed)

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA,
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    screenshots_taken = []
    results = {
        "notes_read": 0, "notes_liked": 0, "notes_collected": 0,
        "collection_folder_created": False, "screenshots": [],
    }
    last_mouse = (640, 450)  # Track mouse position for smooth movement

    try:
        # ───── 1. Go to homepage ─────
        print("[小N] 出发去小红书首页逛逛~")
        page.goto("https://www.xiaohongshu.com/explore",
                   wait_until="domcontentloaded", timeout=30000)
        human_pause("read")  # Wait for page to render
        ss = screenshot(page, "01_home.png")
        screenshots_taken.append(ss)

        # ───── 2. Browse the feed: quick scroll to load cards ─────
        print("[小N] 先滑两下看看有什么...")
        for scroll_i in range(random.randint(1, 3)):
            human_scroll(page, "down")
            if random.random() < 0.4:
                rx = random.uniform(200, 1000)
                ry = random.uniform(150, 750)
                last_mouse = human_mouse_move(page, rx, ry, *last_mouse)
            human_pause("glance")

        ss = screenshot(page, "02_after_browse.png")
        screenshots_taken.append(ss)

        # Scroll back to top
        print("[小N] 回到顶部开始看...")
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        human_pause("scroll")

        # ───── 3. Click into notes one by one ─────
        cards_clicked = 0
        seen_indices = set()
        first_collect = True

        for round_num in range(10):  # Multiple viewport rounds
            if cards_clicked >= args.max_notes:
                break

            visible = get_visible_cards(page)
            print(f"[小N] 当前屏幕看到 {len(visible)} 张卡片")

            if not visible:
                human_scroll(page, "down", total_distance=600)
                human_pause("glance")
                continue

            # Pick 1-3 cards from visible ones (not all — humans are selective)
            unseen = [c for c in visible if c["index"] not in seen_indices]
            if not unseen:
                human_scroll(page, "down", total_distance=600)
                human_pause("scroll")
                continue

            random.shuffle(unseen)
            picks = unseen[:random.randint(1, min(3, len(unseen)))]

            for card_box in picks:
                if cards_clicked >= args.max_notes:
                    break
                seen_indices.add(card_box["index"])
                cx, cy = card_center(card_box)

                print(f"\n[小N] 第{cards_clicked + 1}篇 — 这个看起来有意思，点进去看看...")

                # Move mouse to card and click (human-like curved path)
                try:
                    last_mouse = human_click(page, cx, cy, *last_mouse)
                    human_pause("glance")  # Wait for detail to open
                except Exception as e:
                    print(f"  [点击失败: {e}]")
                    continue

                # Screenshot the note detail
                ss = screenshot(page, f"03_note_{cards_clicked}.png")
                screenshots_taken.append(ss)
                cards_clicked += 1
                results["notes_read"] += 1

                # ── Simulate reading: quick scroll in detail view ──
                print("  [阅读中...]")
                human_pause("glance")

                # Scroll down once or twice to see more content
                for _ in range(random.randint(0, 2)):
                    human_scroll(page, "down", total_distance=random.randint(200, 400))
                    human_pause("glance")

                ss = screenshot(page, f"03_note_{cards_clicked - 1}_more.png")
                screenshots_taken.append(ss)

                # ── Like ──
                if not args.no_like:
                    like_box = find_clickable(page, [
                        ".engage-bar .like-wrapper",
                        "[class*='engage'] [class*='like']",
                        ".note-detail .like-wrapper",
                        "span.like-wrapper",
                    ])
                    if like_box:
                        lx, ly = card_center(like_box)
                        print("  [觉得不错，点个赞~]")
                        last_mouse = human_click(page, lx, ly, *last_mouse)
                        human_pause("glance")
                        results["notes_liked"] += 1
                    else:
                        print("  [没找到点赞按钮]")

                # ── Collect ──
                if not args.no_collect:
                    collect_box = find_clickable(page, [
                        ".engage-bar .collect-wrapper",
                        "[class*='engage'] [class*='collect']",
                        ".note-detail .collect-wrapper",
                        "span.collect-wrapper",
                    ])
                    if collect_box:
                        colx, coly = card_center(collect_box)
                        print("  [收藏一下~]")
                        last_mouse = human_click(page, colx, coly, *last_mouse)
                        human_pause("glance")

                        # Screenshot the collect popup
                        ss = screenshot(page, f"04_collect_{cards_clicked - 1}.png")
                        screenshots_taken.append(ss)

                        # First time: try to create the collection folder
                        if first_collect:
                            print(f"  [尝试创建'{args.folder_name}'...]")
                            human_pause("glance")

                            create_box = find_clickable(page, [
                                "button:has-text('新建')",
                                "span:has-text('新建收藏夹')",
                                "[class*='create-board']",
                                "[class*='add-board']",
                                "[class*='new-board']",
                                ".create-folder",
                            ])
                            if create_box:
                                bx, by = card_center(create_box)
                                last_mouse = human_click(page, bx, by, *last_mouse)
                                human_pause("glance")

                                ss = screenshot(page, "05_create_folder.png")
                                screenshots_taken.append(ss)

                                # Type folder name like a human
                                name_input = page.query_selector(
                                    "input[placeholder*='收藏夹'],"
                                    " input[placeholder*='名称'],"
                                    " input[type='text']"
                                )
                                if name_input:
                                    name_input.fill("")
                                    # Type char by char with variable speed
                                    for ch in args.folder_name:
                                        name_input.type(ch, delay=0)
                                        time.sleep(random.uniform(0.06, 0.18))
                                    human_pause("glance")

                                    ok_box = find_clickable(page, [
                                        "button:has-text('确定')",
                                        "button:has-text('创建')",
                                        "button:has-text('完成')",
                                    ])
                                    if ok_box:
                                        ox, oy = card_center(ok_box)
                                        last_mouse = human_click(page, ox, oy, *last_mouse)
                                        human_pause("glance")
                                        results["collection_folder_created"] = True
                                        print(f"  ['{args.folder_name}' 创建成功!]")
                                    ss = screenshot(page, "05_folder_done.png")
                                    screenshots_taken.append(ss)
                                else:
                                    print("  [没找到输入框]")
                            else:
                                print("  [没找到新建按钮，可能直接收藏了]")
                            first_collect = False

                        results["notes_collected"] += 1
                        print("  [收藏成功!]")
                    else:
                        print("  [没找到收藏按钮]")

                # ── Close the detail overlay ──
                print("  [看完了，关掉...]")
                human_pause("glance")
                page.keyboard.press("Escape")
                human_pause("scroll")

                # Small random delay before next card (natural browsing rhythm)
                if random.random() < 0.15:
                    human_pause("scroll")

            # Scroll to see more cards
            if cards_clicked < args.max_notes:
                print("[小N] 继续往下滑~")
                human_scroll(page, "down")
                human_pause("glance")

        # ───── 4. Done ─────
        ss = screenshot(page, "06_final.png")
        screenshots_taken.append(ss)
        print(f"\n[小N] 逛完啦！总共看了 {cards_clicked} 篇笔记~")

    except Exception as e:
        print(f"[小N] 出错了: {e}")
        import traceback
        traceback.print_exc()
        ss = screenshot(page, "error.png")
        screenshots_taken.append(ss)
    finally:
        human_pause("glance")
        ctx.close()
        pw.stop()

    results["screenshots"] = screenshots_taken
    print("\n" + "=" * 50)
    print("RESULTS_JSON_START")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("RESULTS_JSON_END")


if __name__ == "__main__":
    main()
