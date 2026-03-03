"""
小N 实时浏览器控制 — 通过 CDP 连接常驻 Chrome，每个操作单独执行。

前提：Chrome 已通过 chrome_launcher.py 启动（端口9222）。
本脚本通过 CDP 连接，操作完不关闭浏览器，页面状态保留。

用法：
  python3 xn_live.py start                    # 导航到小红书首页并截图
  python3 xn_live.py ss [名字]                 # 截图
  python3 xn_live.py click X Y                 # 点击
  python3 xn_live.py scroll [down|up] [距离]    # 滚动
  python3 xn_live.py type "文字"               # 输入文字
  python3 xn_live.py press KEY                 # 按键
  python3 xn_live.py goto URL                  # 导航
  python3 xn_live.py comment "评论内容"         # 完整评论流程
  python3 xn_live.py back                      # 返回上一页
  python3 xn_live.py read                      # JS提取帖子结构化内容(标题/正文/评论)
  python3 xn_live.py cards                     # JS读取当前页面可见的笔记卡片列表
  python3 xn_live.py copy                      # 纯键盘Cmd+A/C复制页面文本(低风控)
"""
from __future__ import annotations
import time, json, os, random, sys, argparse, math

# Bypass proxy for local CDP connections
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

SS_DIR = os.path.join(PROJECT_DIR, "tmp", "screenshots")
os.makedirs(SS_DIR, exist_ok=True)

CDP_PORT = 9222


def connect_cdp():
    """Connect to running Chrome via CDP."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, page


def do_screenshot(page, name=None):
    if not name:
        name = f"live_{int(time.time())}.png"
    if not name.endswith('.png'):
        name += '.png'
    path = os.path.join(SS_DIR, name)
    page.screenshot(path=path)
    print(path)
    return path


# ── Human-like mouse/click (inline, no dependency on xn_browse global state) ──

def _bezier_point(t, p0, p1, p2, p3):
    u = 1 - t
    return u**3*p0 + 3*u**2*t*p1 + 3*u*t**2*p2 + t**3*p3

def human_move(page, to_x, to_y, from_x=640, from_y=450):
    dx, dy = to_x - from_x, to_y - from_y
    dist = math.sqrt(dx*dx + dy*dy)
    steps = max(8, min(25, int(dist / 20)))
    perp_x, perp_y = -dy/max(dist,1), dx/max(dist,1)
    curve = random.uniform(-0.2, 0.2) * dist
    cp1x = from_x + dx*0.25 + perp_x*curve*random.uniform(0.5,1.5)
    cp1y = from_y + dy*0.25 + perp_y*curve*random.uniform(0.5,1.5)
    cp2x = from_x + dx*0.75 + perp_x*curve*random.uniform(0.3,0.8)
    cp2y = from_y + dy*0.75 + perp_y*curve*random.uniform(0.3,0.8)
    for i in range(steps+1):
        t = i/steps
        te = t*t*(3-2*t)
        x = _bezier_point(te, from_x, cp1x, cp2x, to_x)
        y = _bezier_point(te, from_y, cp1y, cp2y, to_y)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.005, 0.015))

def human_click(page, x, y):
    human_move(page, x, y)
    time.sleep(random.uniform(0.05, 0.12))
    page.mouse.down()
    time.sleep(random.uniform(0.04, 0.10))
    page.mouse.up()

def human_scroll(page, direction="down", distance=400):
    sign = 1 if direction == "down" else -1
    chunks = random.randint(3, 5)
    per = distance // chunks
    for _ in range(chunks):
        page.mouse.wheel(0, (per + random.randint(-10,10)) * sign)
        time.sleep(random.uniform(0.05, 0.15))
    time.sleep(0.3)


def do_read(page):
    """读取当前打开的笔记详情：标题、正文、作者、评论、配图URL"""
    data = page.evaluate("""() => {
        const result = {title: '', author: '', content: '', tags: [], comments: [], images: [], likes: '', collects: '', comment_count: ''};

        // 优先在笔记详情弹窗内查找（弹窗覆盖在首页上）
        // 小红书弹窗的容器 class 经常变，用多种方式定位
        let scope = document.querySelector('.note-detail-mask');
        if (!scope) scope = document.querySelector('[id*="noteContainer"]');
        if (!scope) scope = document.querySelector('[class*="note-detail"]');
        if (!scope) {
            // 找包含 engage-bar 的最近祖先容器
            const engage = document.querySelector('.interactions.engage-bar');
            if (engage) scope = engage.closest('[class*="container"]') || engage.parentElement.parentElement.parentElement;
        }
        if (!scope) scope = document;

        // 标题 — 用 id 最可靠
        const titleEl = scope.querySelector('#detail-title');
        if (titleEl) {
            result.title = titleEl.textContent.trim();
        } else {
            // 备选：找弹窗内大字标题
            const h1 = scope.querySelector('h1, [class*="title"]:not(a)');
            if (h1 && h1.textContent.trim().length > 2) result.title = h1.textContent.trim();
        }

        // 作者
        const authorEl = scope.querySelector('.author-wrapper .username') ||
                          scope.querySelector('[class*="author"] [class*="name"]') ||
                          scope.querySelector('.info .name') ||
                          scope.querySelector('a.name');
        if (authorEl) result.author = authorEl.textContent.trim();

        // 正文 — #detail-desc 最可靠
        const descEl = scope.querySelector('#detail-desc') ||
                        scope.querySelector('[class*="desc"][class*="detail"]') ||
                        scope.querySelector('.note-text');
        if (descEl) {
            const walker = document.createTreeWalker(descEl, NodeFilter.SHOW_TEXT, null);
            const parts = [];
            let node;
            while (node = walker.nextNode()) {
                const t = node.textContent.trim();
                if (t) parts.push(t);
            }
            result.content = parts.join('\\n');
        }

        // 正文备选：如果上面没拿到，试试取弹窗右侧所有段落
        if (!result.content) {
            const paragraphs = scope.querySelectorAll('p, span.content, [class*="content"]');
            const texts = [];
            paragraphs.forEach(p => {
                const t = p.textContent.trim();
                if (t && t.length > 10 && !t.includes('条评论') && !t.includes('说点什么')) texts.push(t);
            });
            if (texts.length) result.content = texts.join('\\n');
        }

        // 话题标签
        scope.querySelectorAll('a[class*="tag"], a.tag, [class*="hash-tag"], a[href*="tag"]').forEach(el => {
            const t = el.textContent.trim();
            if (t && (t.startsWith('#') || t.startsWith('＃'))) result.tags.push(t);
        });

        // 互动数据 — 从 engage-bar 的 span 中提取
        const engageBar = scope.querySelector('.engage-bar, .interactions, [class*="engage"]');
        if (engageBar) {
            const spans = engageBar.querySelectorAll('span.count, [class*="count"]');
            spans.forEach((s, i) => {
                const v = s.textContent.trim();
                if (i === 0) result.likes = v;
                else if (i === 1) result.collects = v;
                else if (i === 2) result.comment_count = v;
            });
        }
        // 备选：like-wrapper
        if (!result.likes) {
            const el = scope.querySelector('[class*="like-wrapper"] span, [class*="like"] .count');
            if (el) result.likes = el.textContent.trim();
        }
        if (!result.collects) {
            const el = scope.querySelector('[class*="collect-wrapper"] span, [class*="collect"] .count');
            if (el) result.collects = el.textContent.trim();
        }

        // 评论
        const commentEls = scope.querySelectorAll('[class*="comment-item"], .parent-comment, [class*="commentItem"]');
        commentEls.forEach((el, i) => {
            if (i >= 20) return;
            const nameEl = el.querySelector('.name, .author-name, [class*="name"]');
            const textEl = el.querySelector('.content, .note-text, [class*="content"]');
            if (nameEl && textEl) {
                result.comments.push({
                    author: nameEl.textContent.trim(),
                    text: textEl.textContent.trim()
                });
            }
        });

        // 配图URL
        const imgEls = scope.querySelectorAll('.swiper-slide img, [class*="slide"] img, [class*="carousel"] img');
        imgEls.forEach(img => {
            const src = img.src || img.getAttribute('data-src') || '';
            if (src && src.includes('xhscdn') && !result.images.includes(src)) result.images.push(src);
        });
        // 备选：大图
        if (result.images.length === 0) {
            scope.querySelectorAll('img[src*="xhscdn"]').forEach(img => {
                if (img.width > 200 && !result.images.includes(img.src)) result.images.push(img.src);
            });
        }

        return result;
    }""")

    # 输出为JSON
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def do_read_cards(page):
    """读取当前页面可见的笔记卡片列表（首页/搜索结果的瀑布流）"""
    cards = page.evaluate("""() => {
        const results = [];
        // 小红书首页卡片选择器
        const sections = document.querySelectorAll('section.note-item, [class*="note-item"], .feeds-container section');
        sections.forEach((sec, i) => {
            const rect = sec.getBoundingClientRect();
            // 只取视口内可见的
            if (rect.top > window.innerHeight || rect.bottom < 0) return;

            const titleEl = sec.querySelector('.title, [class*="title"] span, a[class*="title"]');
            const authorEl = sec.querySelector('.author-wrapper .name, [class*="author"] .name, .name');
            const likeEl = sec.querySelector('[class*="like"] .count, .like-wrapper .count, [class*="count"]');
            const coverEl = sec.querySelector('img');
            const linkEl = sec.querySelector('a[href*="/explore/"], a[href*="/discovery/item/"]');

            results.push({
                index: i,
                title: titleEl ? titleEl.textContent.trim() : '',
                author: authorEl ? authorEl.textContent.trim() : '',
                likes: likeEl ? likeEl.textContent.trim() : '',
                cover: coverEl ? (coverEl.src || '') : '',
                href: linkEl ? linkEl.href : '',
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                w: Math.round(rect.width),
                h: Math.round(rect.height)
            });
        });
        return results;
    }""")

    print(json.dumps(cards, ensure_ascii=False, indent=2))
    return cards


def do_copy(page):
    """纯键盘操作：Cmd+A全选 → Cmd+C复制 → 从剪贴板读取文本。零JS，低风控。"""
    import subprocess

    # 先点击右侧内容区域确保焦点在正文（避免选中侧边栏）
    # 在笔记详情弹窗中，右半部分约 x=750, y=400
    human_click(page, 750, 400)
    time.sleep(0.3)

    # Cmd+A 全选当前焦点区域的文本
    page.keyboard.press("Meta+A")
    time.sleep(0.2)

    # Cmd+C 复制
    page.keyboard.press("Meta+C")
    time.sleep(0.3)

    # 从系统剪贴板读取
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        text = result.stdout
    except Exception as e:
        print(f"ERROR: 读取剪贴板失败: {e}")
        return

    # 点一下空白处取消选中
    page.keyboard.press("Escape")
    time.sleep(0.1)

    if text.strip():
        print(text)
    else:
        print("ERROR: 剪贴板为空")


def do_comment(page, text):
    """完整评论流程"""
    # Find contenteditable
    for attempt in range(3):
        box = page.evaluate("""() => {
            const eds = document.querySelectorAll('[contenteditable="true"]');
            let best = null;
            for (const el of eds) {
                const r = el.getBoundingClientRect();
                if (r.width > 30 && r.height > 10 && r.y > 300) {
                    if (!best || r.y > best.y) best = {x:r.x,y:r.y,w:r.width,h:r.height};
                }
            }
            return best;
        }""")
        if box: break
        time.sleep(1.5)

    if not box:
        print("ERROR: 找不到评论输入框")
        return

    # Click input
    human_click(page, box['x']+box['w']/2, box['y']+box['h']/2)
    time.sleep(1.0)

    # Re-find expanded
    box2 = page.evaluate("""() => {
        const eds = document.querySelectorAll('[contenteditable="true"]');
        let best = null;
        for (const el of eds) {
            const r = el.getBoundingClientRect();
            if (r.width > 30 && r.height > 10 && r.y > 300) {
                if (!best || r.y > best.y) best = {x:r.x,y:r.y,w:r.width,h:r.height};
            }
        }
        return best;
    }""")
    if box2 and box2['w'] > box['w'] + 50:
        human_click(page, box2['x']+box2['w']/2, box2['y']+box2['h']/2)
        time.sleep(0.5)

    # Type
    for ch in text:
        page.keyboard.type(ch, delay=0)
        time.sleep(random.uniform(0.03, 0.08))
    time.sleep(0.5)

    # Send
    btn = page.evaluate("""() => {
        for (const el of document.querySelectorAll('button,span,div,a')) {
            if ((el.textContent||'').trim() === '发送') {
                const r = el.getBoundingClientRect();
                if (r.width>15 && r.height>15 && r.y>300) return {x:r.x,y:r.y,w:r.width,h:r.height};
            }
        }
        return null;
    }""")
    if btn:
        human_click(page, btn['x']+btn['w']/2, btn['y']+btn['h']/2)
    else:
        page.keyboard.press("Control+Enter")

    time.sleep(2.0)
    print("OK: 评论已发送")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=[
        "start", "ss", "screenshot", "click", "scroll",
        "type", "press", "goto", "comment", "back", "move",
        "read", "cards", "copy"
    ])
    parser.add_argument("args", nargs="*", default=[])
    parsed = parser.parse_args()
    action = parsed.action
    args = parsed.args

    pw, browser, page = connect_cdp()

    try:
        if action == "start":
            page.goto("https://www.xiaohongshu.com/explore",
                       wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.0)
            do_screenshot(page, "live_home.png")

        elif action in ("ss", "screenshot"):
            name = args[0] if args else None
            do_screenshot(page, name)

        elif action == "click":
            if len(args) < 2:
                print("ERROR: click X Y"); return
            human_click(page, float(args[0]), float(args[1]))
            time.sleep(1.5)
            do_screenshot(page, "live_after_click.png")

        elif action == "scroll":
            # scroll [down|up] [距离] [x] [y]  — 可选先移鼠标到(x,y)再滚
            d = args[0] if args else "down"
            dist = int(args[1]) if len(args) > 1 else 400
            if len(args) >= 4:
                page.mouse.move(float(args[2]), float(args[3]))
                time.sleep(0.1)
            human_scroll(page, d, dist)
            do_screenshot(page, "live_after_scroll.png")

        elif action == "type":
            if not args: print("ERROR: need text"); return
            text = " ".join(args)
            for ch in text:
                page.keyboard.type(ch, delay=0)
                time.sleep(random.uniform(0.03, 0.08))

        elif action == "press":
            if not args: print("ERROR: need key"); return
            page.keyboard.press(args[0])
            time.sleep(0.5)
            do_screenshot(page, "live_after_press.png")

        elif action == "goto":
            if not args: print("ERROR: need URL"); return
            page.goto(args[0], wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.0)
            do_screenshot(page, "live_after_goto.png")

        elif action == "comment":
            if not args: print("ERROR: need comment text"); return
            do_comment(page, " ".join(args))
            do_screenshot(page, "live_after_comment.png")

        elif action == "back":
            page.go_back()
            time.sleep(2.0)
            do_screenshot(page, "live_after_back.png")

        elif action == "move":
            if len(args) < 2:
                print("ERROR: move X Y"); return
            human_move(page, float(args[0]), float(args[1]))

        elif action == "read":
            do_read(page)

        elif action == "cards":
            do_read_cards(page)

        elif action == "copy":
            do_copy(page)

    finally:
        # DON'T close browser! Just disconnect.
        browser.close()  # This disconnects CDP, doesn't kill Chrome
        pw.stop()


if __name__ == "__main__":
    main()
