"""
小N 创作中心探索脚本 — 逐步点击创作中心每个元素，截图记录。

创作中心是独立站点 creator.xiaohongshu.com，布局与主站不同。
使用 CDP 连接（端口9222），不用 Playwright。
"""
from __future__ import annotations
import time, json, os, random, sys, argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from xn_browse import (
    human_click, human_mouse_move, human_pause, human_scroll, USER_DATA
)
import xn_browse

SS_DIR = os.path.join(PROJECT_DIR, "tmp", "screenshots", "creator_explore")
os.makedirs(SS_DIR, exist_ok=True)

step_counter = 0

def ss(page, name):
    global step_counter
    step_counter += 1
    fname = f"{step_counter:02d}_{name}"
    path = os.path.join(SS_DIR, fname)
    page.screenshot(path=path)
    print(f"  [截图] {fname}")
    return path


def main():
    xn_browse.SPEED = 2.0

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
    screenshots = []

    try:
        # ===== 1. 创作中心首页 =====
        print("[小N] 进入创作中心~")
        page.goto("https://creator.xiaohongshu.com",
                   wait_until="domcontentloaded", timeout=30000)
        time.sleep(3.0)
        screenshots.append(ss(page, "creator_home.png"))

        # Scroll down to see data overview
        human_scroll(page, "down", total_distance=400)
        human_pause("glance")
        screenshots.append(ss(page, "creator_home_scrolled.png"))

        # ===== 2. 笔记管理 =====
        print("\n[小N] 点击 笔记管理...")
        # From XHS_UI_MAP: 笔记管理 约(80, 215)
        last_mouse = human_click(page, 80, 215, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "note_management.png"))

        # Scroll to see more
        human_scroll(page, "down", total_distance=300)
        human_pause("glance")
        screenshots.append(ss(page, "note_management_scrolled.png"))

        # ===== 3. 数据看板 =====
        print("\n[小N] 点击 数据看板...")
        last_mouse = human_click(page, 80, 263, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "data_dashboard.png"))

        # Check if it expands into sub-menu
        human_pause("glance")
        screenshots.append(ss(page, "data_dashboard_expanded.png"))

        # Try clicking sub-items if they appeared
        # 数据看板可能有子菜单：账号数据、笔记数据等
        human_scroll(page, "down", total_distance=300)
        screenshots.append(ss(page, "data_dashboard_content.png"))

        # ===== 4. 数据分析页面 =====
        print("\n[小N] 进入数据分析页面...")
        page.goto("https://creator.xiaohongshu.com/statistics/data-analysis",
                   wait_until="domcontentloaded", timeout=30000)
        time.sleep(3.0)
        screenshots.append(ss(page, "data_analysis.png"))

        human_scroll(page, "down", total_distance=300)
        screenshots.append(ss(page, "data_analysis_scrolled.png"))

        # ===== 5. 活动中心 =====
        print("\n[小N] 点击 活动中心...")
        last_mouse = human_click(page, 80, 313, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "activity_center.png"))

        # ===== 6. 笔记灵感 =====
        print("\n[小N] 点击 笔记灵感...")
        last_mouse = human_click(page, 80, 363, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "note_inspiration.png"))

        human_scroll(page, "down", total_distance=300)
        screenshots.append(ss(page, "note_inspiration_scrolled.png"))

        # ===== 7. 创作学院 =====
        print("\n[小N] 点击 创作学院...")
        last_mouse = human_click(page, 80, 413, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "creator_academy.png"))

        # ===== 8. 创作百科 =====
        print("\n[小N] 点击 创作百科...")
        last_mouse = human_click(page, 80, 463, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "creator_wiki.png"))

        # ===== 9. 发布页面 =====
        print("\n[小N] 进入发布页面...")
        page.goto("https://creator.xiaohongshu.com/publish/publish",
                   wait_until="domcontentloaded", timeout=30000)
        time.sleep(3.0)
        screenshots.append(ss(page, "publish_video_tab.png"))

        # Click "上传图文" tab
        print("  点击 上传图文 Tab...")
        last_mouse = human_click(page, 390, 100, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "publish_image_tab.png"))

        # Click "写长文" tab
        print("  点击 写长文 Tab...")
        last_mouse = human_click(page, 475, 100, *last_mouse)
        time.sleep(2.0)
        screenshots.append(ss(page, "publish_longtext_tab.png"))

        # ===== 10. 回到首页看"发布笔记"按钮 =====
        print("\n[小N] 回到创作中心首页...")
        last_mouse = human_click(page, 80, 168, *last_mouse)
        time.sleep(2.0)

        # Click the "发布笔记" red button to see dropdown
        print("  点击 发布笔记 按钮...")
        last_mouse = human_click(page, 105, 98, *last_mouse)
        time.sleep(1.5)
        screenshots.append(ss(page, "publish_button_dropdown.png"))

        # Press Escape to close dropdown
        page.keyboard.press("Escape")
        human_pause("glance")

        # ===== 11. 探索用户信息区域 =====
        print("\n[小N] 查看用户信息区域...")
        last_mouse = human_click(page, 80, 168, *last_mouse)  # Go to homepage
        time.sleep(2.0)
        screenshots.append(ss(page, "creator_user_info.png"))

        # ===== Done =====
        print(f"\n[小N] 创作中心探索完成！共 {len(screenshots)} 张截图")

    except Exception as e:
        print(f"[小N] 出错了: {e}")
        import traceback
        traceback.print_exc()
        screenshots.append(ss(page, "error.png"))
    finally:
        human_pause("glance")
        ctx.close()
        pw.stop()

    print(f"\n截图目录: {SS_DIR}")
    print(f"共 {len(screenshots)} 张截图")


if __name__ == "__main__":
    main()
