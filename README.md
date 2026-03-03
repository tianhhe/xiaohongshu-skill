# 小红书 AI 电子分身 🤖

> 让 AI 像真人一样刷小红书——浏览、点赞、收藏、评论、发帖，全自动。

这是一个 **Claude Code Skill**，让 AI 拥有自己的名字和人格，在小红书上像真人一样浏览互动。不是爬虫，不是 API 调用，而是真的打开浏览器、移动鼠标、敲键盘——连滚动都是贝塞尔曲线的。

---

## ✨ 能做什么

```
🔍 自主浏览    像真人一样刷首页、搜索、看帖子
💬 智能评论    读完帖子内容，生成有温度的评论（不是"写得好棒"）
❤️ 互动操作    点赞、收藏、关注、取关
📝 创作发帖    AI 写文案 + AI 配图 + 自动发布
🎬 视频制作    图片合成视频，支持文字+BGM
📊 数据查看    创作者中心数据一键读取
🔔 通知处理    查看评论通知，批量回复
🤖 Subagent   浏览摘要/截图读图/并发回复/内容审查，主对话轻量高效
```

---

## 🏗 架构一览

```
┌─────────────────────────────────────────────────┐
│  Claude Code / AI Agent                         │
│  ┌───────────────┐  ┌────────────────────────┐  │
│  │  SKILL.md     │  │  XHS_UI_MAP.md         │  │
│  │  人格 & 流程  │  │  界面记忆（按钮坐标） │  │
│  └───────┬───────┘  └────────────┬───────────┘  │
│          │                       │               │
│          ▼                       ▼               │
│  ┌────────────────────────────────────────────┐  │
│  │            scripts/ 脚本层                 │  │
│  │                                            │  │
│  │  xn_live.py      实时 CDP 控制（单步操作）│  │
│  │  xn_browse.py    人类模拟浏览引擎         │  │
│  │  cdp_publish.py  搜索/详情/评论/通知      │  │
│  │  publish_pipeline.py  一键发布管道        │  │
│  │  image_generator.py   AI 配图             │  │
│  │  video_maker.py       视频合成            │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                          │
│                       ▼                          │
│  ┌────────────────────────────────────────────┐  │
│  │  Chrome (CDP 9222)                         │  │
│  │  贝塞尔曲线鼠标 · 不均匀滚动 · 自然停顿  │  │
│  └────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 安装

```bash
# 克隆仓库到 Claude Code skills 目录
git clone https://github.com/tianthe/xiaohongshu-skill.git \
  ~/.claude/skills/xiaohongshu-skill

# 安装依赖
cd ~/.claude/skills/xiaohongshu-skill
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 2. 启动浏览器 & 登录

```bash
# 启动 Chrome（有窗口模式，端口 9222）
python scripts/chrome_launcher.py

# 首次登录（扫码）
python scripts/cdp_publish.py login
```

### 3. 初始化人格

在 Claude Code 中对话：

```
> 小红书电子分身
```

AI 会引导你设置：名字、性格、语气风格、兴趣领域、写作偏好。

### 4. 开始玩

```
> 去小红书刷一刷          # 自主浏览模式
> 发一篇关于春天的笔记    # 创作模式
> 回复昨天帖子的评论      # 互动模式
> 看看我的数据怎么样      # 数据模式
```

---

## 🎭 AI 人格系统

每个分身有独立的人格配置（`config/persona.json`）：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `name` | AI 的名字 | 小N |
| `personality` | 性格描述 | 活泼好奇，幽默但不失温柔 |
| `tone` | 语气风格 | 轻松俏皮 |
| `interests` | 感兴趣的领域（最多5个） | 科技/AI, 人文社科, 旅行 |
| `writing_style` | 写作风格 | 随笔感悟型 |
| `auto_behaviors` | 自主浏览时的自动行为 | 自动点赞、收藏感兴趣的内容 |

AI 会用这个人格来决定：看到什么内容会点赞、评论怎么写、帖子什么风格。

---

## 🖱 为什么不会被封？

核心理念：**不是自动化工具，是模拟真人**。

- **鼠标移动**：贝塞尔曲线轨迹，不是直线瞬移
- **滚动**：分段不均匀滚动，带随机抖动
- **点击**：鼠标按下和抬起之间有随机延迟
- **打字**：逐字输入，每个字之间 30-80ms 随机间隔
- **停顿**：看帖子会"阅读"几秒，像真人在看内容
- **无 JS 注入**：浏览和互动操作尽量用键鼠模拟，不直接操作 DOM

---

## 📂 项目结构

```
xiaohongshu-skill/
├── SKILL.md                  # Skill 定义（Claude Code 入口）
├── XHS_UI_MAP.md             # 界面地图（按钮坐标、布局记忆）
├── config/
│   ├── persona.json.example  # 人格配置模板
│   └── accounts.json.example # 多账号配置模板
├── scripts/
│   ├── xn_live.py            # 实时 CDP 控制（核心）
│   ├── xn_browse.py          # 人类模拟浏览引擎
│   ├── xn_deep_browse.py     # 深度浏览（逐帖截图+评论）
│   ├── cdp_publish.py        # 搜索/详情/评论/通知/数据
│   ├── publish_pipeline.py   # 一键发布管道
│   ├── chrome_launcher.py    # Chrome 生命周期管理
│   ├── image_generator.py    # AI 配图（阿里云）
│   ├── video_maker.py        # 视频合成（ffmpeg）
│   ├── persona_manager.py    # 人格配置管理
│   └── account_manager.py    # 多账号管理
└── tmp/                      # 临时文件（截图、草稿等）
```

---

## 🔧 核心脚本说明

### `xn_live.py` — 实时浏览器控制

通过 CDP 连接常驻 Chrome，每个操作单独执行，页面状态保留。

```bash
python scripts/xn_live.py start              # 打开小红书首页
python scripts/xn_live.py ss [名字]           # 截图
python scripts/xn_live.py click X Y           # 点击
python scripts/xn_live.py scroll down 400     # 滚动
python scripts/xn_live.py type "文字"         # 输入
python scripts/xn_live.py read                # 读取帖子内容
python scripts/xn_live.py cards               # 读取卡片列表
python scripts/xn_live.py comment "评论"      # 发评论
python scripts/xn_live.py back                # 返回
```

### `publish_pipeline.py` — 一键发布

```bash
# 图文发布
python scripts/publish_pipeline.py \
  --title-file title.txt \
  --content-file content.txt \
  --images "/path/to/img1.png" "/path/to/img2.png"

# 视频发布
python scripts/publish_pipeline.py \
  --title-file title.txt \
  --content-file content.txt \
  --video "/path/to/video.mp4"

# 预览模式（不自动点发布）
python scripts/publish_pipeline.py --preview \
  --title "标题" --content "正文" --image-urls "URL"
```

### `cdp_publish.py` — 搜索/互动/数据

```bash
# 搜索
python scripts/cdp_publish.py search-feeds --keyword "关键词"

# 笔记详情
python scripts/cdp_publish.py read-note-detail --feed-id ID --xsec-token TOKEN

# 点赞/收藏/关注
python scripts/cdp_publish.py like-note --feed-id ID --xsec-token TOKEN
python scripts/cdp_publish.py collect-note --feed-id ID --xsec-token TOKEN
python scripts/cdp_publish.py follow-user --user-id UID

# 数据看板
python scripts/cdp_publish.py content-data
```

---

## 🎨 AI 配图 & 视频

### 配图

需要配置阿里云图片生成 API（在 `persona.json` 的 `image_api` 中设置）。

```bash
# 单张生成
python scripts/image_generator.py generate --prompt "春天的田野" --output cover.png

# 为帖子批量配图
python scripts/image_generator.py for-post --title "标题" --content "正文" --count 3
```

### 视频

需要安装 ffmpeg。

```bash
# 检查环境
python scripts/video_maker.py check

# 图片合成视频
python scripts/video_maker.py slideshow \
  --images img1.jpg img2.jpg img3.jpg \
  --texts "第一页" "第二页" "第三页" \
  --output video.mp4 \
  --music bgm.mp3
```

---

## 🤖 Subagent 并发架构

为了避免大量图片和数据占满主对话上下文，本 Skill 在以下四个环节使用 subagent：

| 场景 | Subagent 做什么 | 主对话收到什么 |
|------|----------------|---------------|
| 自主浏览结果 | 从完整 JSON 中筛选最匹配人格兴趣的 Top 3 | 3条摘要 + feed_id |
| 截图读图 | 读取截图文件，用文字描述页面状态 | 一段文字描述 |
| 批量回复评论 | 每条评论独立并行生成回复 | 汇总后一次确认 |
| 发帖内容审查 | 检查字数/违规词/落款格式 | ✅/❌ 逐项结论 |

这样主对话始终保持轻量，长时间操作也不会撑爆上下文。

---

## 📖 界面记忆系统

`XHS_UI_MAP.md` 是 AI 的"界面记忆"——通过实际操作逐步积累的按钮位置、页面布局、导航路径。

每次操作时：
1. **操作前**：用 subagent 按需读取 `XHS_UI_MAP.md` 中与当前任务相关的片段
2. **操作后**：用 subagent 把截图中发现的新信息追加到 `XHS_UI_MAP.md`

已记录的界面：
- 首页 `/explore`（侧边栏、搜索框、瀑布流）
- 个人主页（头像、Tab栏、笔记列表）
- 笔记详情弹窗（正文区、评论区、互动栏）
- 一级评论 & 二级回复的完整操作流程
- 搜索页、通知页、收藏页
- 创作者中心全部子页面

---

## ⚠️ 注意事项

1. **仅供学习研究**，请遵守小红书平台规则
2. **Cookie 安全**：登录态存在本地 `playwright_data/`，不要泄露
3. **所有 AI 生成内容必须标注**：评论末尾加 `（ai回复，仅供参考）`
4. **发布前必须用户确认**：AI 不会自动发布任何内容
5. **Python 3.9+** 兼容（脚本使用 `from __future__ import annotations`）

---

## 🙏 致谢

- 原始项目：[Angiin/Post-to-xhs](https://github.com/Angiin/Post-to-xhs)
- AI 引擎：[Claude](https://claude.ai) by Anthropic

## 📄 License

MIT
