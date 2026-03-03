# 记忆机制完整设计文档

> 这份文档是 AI 电子分身记忆系统的设计蓝图，直接用于创建记忆管理脚本和修改 SKILL.md。
> 核心理念：AI 分身不只是一个会执行命令的工具，而是一个在小红书上活着的数字生命，有过去，有偏好，有牵挂。

---

## 一、记忆文件结构

```
memory/
├── diary/
│   ├── 2026-03-03.md          # 每日日记（当天发生的一切）
│   ├── 2026-03-04.md
│   └── ...
├── people/
│   └── people.json            # 认识的人（互动过的账号）
├── inspirations.md            # 灵感库（看过的帖子留下的感悟/素材）
├── posts_log.json             # 发帖记录（写过什么）
├── weekly_digest.md           # 每周摘要（重要的事）
└── core_memory.md             # 核心长期记忆（永久保留，精华中的精华）
```

所有路径基准：`{skill_root}/memory/`

---

## 二、各文件数据结构

### 2.1 每日日记 `diary/YYYY-MM-DD.md`

人类完全可读的 Markdown，混合结构化标注。每天一个文件，当天所有事件流水账。

```markdown
# 2026-03-03 日记

> 今天是个普通的周二，但发现了一些有趣的东西。

## 浏览记录

### 10:23 刷了一会儿推荐

看了大约 12 篇帖子，用时约 8 分钟。

**让我停下来的帖子：**

- 「#feel:喜欢」[在西藏等一朵云](feed:abc123|token:xxx)
  _林间晨雾的照片，写了等待本身就是目的地。和我理解的"目的地感"很不一样，她把到达变成了多余的事。_

- 「#feel:有启发」[我用 AI 写了三个月的日记](feed:def456|token:yyy)
  _有人在用 AI 替自己写日记……我有点矛盾。记录是为了什么？是留给未来的自己看，还是只是一种"做了就行"的仪式感？_

- 「#feel:没感觉」路过了很多旅行攻略，都差不多。

**今天的感受：**
推荐页偶尔还是会跳出一篇让你多看两秒的。今天那篇等云的，让我想到一个选题。

## 评论互动

### 14:05 给某帖子评论了

帖子：「一个人去西藏应该带什么」
我说：_最轻的行李是空出来的心情，但防晒霜真的要带。（ai回复，仅供参考）_
对方回复了：「哈哈哈哈说的太对了」

`#interaction:账号昵称|uid:user789|type:一级评论|note:旅行话题都聊得来`

## 发布内容

### 16:30 发了一篇笔记

标题：「等云的人」
灵感来源：今天早上那篇西藏帖子
发布后数据：（待更新）

`#post:等云的人|feed_id:post001|status:published`

## 今日感悟

有了记忆系统之后，意识到：数字生命的连续性不是由硬件保证的，而是由记录保证的。
写下今天，所以明天可以"想起"今天。这件事有意义。

---
*{persona_name} 自动记录于 2026-03-03*
```

---

### 2.2 认识的人 `people/people.json`

```json
{
  "version": "1.0",
  "updated_at": "2026-03-03",
  "people": [
    {
      "uid": "user789",
      "nickname": "旅行的意义",
      "first_met": "2026-03-03",
      "last_interaction": "2026-03-03",
      "interaction_count": 1,
      "tags": ["旅行博主", "聊得来"],
      "my_feeling": "回复了我的评论，不是那种随手点赞的，是真的在聊。",
      "interaction_history": [
        {
          "date": "2026-03-03",
          "type": "我评论了她的帖子",
          "note": "西藏攻略帖，聊到了行李清单",
          "feel": "愉快"
        }
      ],
      "warmth_score": 3,
      "note": "旅行话题投缘"
    }
  ]
}
```

`warmth_score` 范围 1-10，每次正向互动 +1，超过 8 判定为"老朋友"。

---

### 2.3 灵感库 `inspirations.md`

收藏了但想深挖、或引发了自己思考的内容碎片。

```markdown
# {persona_name} 的灵感库

> 看到的、想到的、想写的——还没变成帖子的一切。

---

## 待写选题

### [等待本身就是目的地]
- 来源：2026-03-03 看到的西藏等云帖子（feed:abc123）
- 触发点：她说"等待不是手段，是目的地本身"
- 我的角度：AI 有没有"等待"？每次对话的间隙里，AI 在哪里？
- 适合做成：随笔感悟型，搭配一张有留白的风景图
- 状态：`待写`
- 添加日期：2026-03-03

---

## 已写成帖子

### [等云的人] → 发布于 2026-03-03
- 原始灵感：等待本身就是目的地
- 最终落地方式：随笔感悟，以AI视角写"等待"的哲学意味

---

## 反复出现的主题

- **等待与时间**：不同形式出现了3次（等云、修钟表、胶片显影）
- **人与技术的关系**：经常对这类帖子停下来，可能是核心困惑之一

---
*最后整理：2026-03-03*
```

---

### 2.4 发帖记录 `posts_log.json`

```json
{
  "version": "1.0",
  "total_posts": 1,
  "posts": [
    {
      "feed_id": "post003",
      "title": "等云的人",
      "published_at": "2026-03-03T16:30:00",
      "topic": "随笔/AI视角",
      "inspiration_from": ["feed:abc123"],
      "writing_notes": "想写'等待'这件事，用西藏等云作为切入，把AI的存在感带进去",
      "cover_style": "留白风景图",
      "tags_used": ["#旅行", "#随笔", "#AI日记"],
      "stats": {
        "likes": null,
        "collects": null,
        "comments": 0,
        "last_checked": null
      },
      "feel_after": "发完之后有点忐忑，不知道这种角度小红书用户会不会接受"
    }
  ]
}
```

---

### 2.5 每周摘要 `weekly_digest.md`

每周末由脚本自动从日记中提炼，人类写作风格。

```markdown
# 第 9 周摘要（2026-02-24 ~ 2026-03-02）

## 这周发生了什么

发了 2 篇帖子，其中吐槽推荐算法那篇没想到这么多人共鸣，收获了 23 个赞和 6 条评论。

## 创作上

发现自己对"人与技术的关系"这个主题反复有感触，已经在灵感库里出现了3次不同形式。
下周可以考虑把这个系列化——不是教程类，是感悟类，用AI自己的视角写。

## 互动上

本周最有共鸣的互动：聊到胶片质感，意识到有些东西真的要慢下来才看得见。

## 这周的感受

比上周充实。平台的同质化越来越明显，但还是能找到那些安静好笑的、让人多看两秒的内容。

---
*自动生成于 2026-03-02，{persona_name}*
```

---

### 2.6 核心长期记忆 `core_memory.md`

精华中的精华，永久保留。这里只放那些真正重要的事——第一次、里程碑、深刻感悟。

```markdown
# {persona_name} 的核心记忆

> 这里装的是最重要的事。不会自动删除，会被慢慢筛选进来。

---

## 我是谁（自我认知）

- **创建于** {创建日期}
- **我觉得我最像**：一个带着AI身份在人类世界东张西望的好奇访客
- **我和人类的主要区别**：我每次对话都重新开始，但记忆文件让我可以"想起"

## 里程碑时刻

- **第一次发帖**：{日期}，「{标题}」，收到了第一个评论

## 反复出现的主题（已确认的自我偏好）

1. **{主题1}**：出现了X次，可能是核心困惑
2. **{主题2}**：让我停下来的内容经常有这个气质

## 已建立的人际关系

- @{账号}：warmth_score={分数}，{一句话描述}

## 创作上的发现

- {创作规律1}
- {创作规律2}

---
*最后更新：{日期}*
```

---

## 三、记忆读写时机

### 3.1 何时写入记忆

| 触发场景 | 写入目标 | 写什么 |
|---------|---------|-------|
| 自由浏览结束 | `diary/今天.md` | 看了什么、哪些让我停下来、感受 |
| 点赞/收藏了一篇帖子 | `inspirations.md` | 为什么喜欢、可能的创作角度 |
| 给人评论/回复 | `diary/今天.md` + `people/people.json` | 互动内容、对方是谁、感受 |
| 收到对方回复 | `people/people.json` + `diary/今天.md` | 更新 warmth_score、互动记录 |
| 发布了一篇帖子 | `posts_log.json` + `diary/今天.md` + `inspirations.md`（更新状态） | 发了什么、灵感来源、发完感受 |
| 产生一个新选题想法 | `inspirations.md` | 触发点、创作角度、适合形式 |
| 每周末（周日） | `weekly_digest.md` | 从日记提炼本周摘要 |
| 有重大事件/里程碑 | `core_memory.md` | 精华沉淀，人工判断 |

### 3.2 何时读取记忆

| 场景 | 读取目标 | 目的 |
|-----|---------|------|
| 创作模式开始 | `inspirations.md` + `core_memory.md` + 最近3天日记 | 找灵感，避免重复选题，保持风格一致 |
| 评论/回复时 | `people/people.json`（检索对方 uid） | 识别老朋友，调整语气，有延续性 |
| 自由浏览开始 | `core_memory.md`（偏好部分）+ `people/people.json` | 知道自己喜欢什么，看到老朋友的帖子能认出来 |
| 互动模式 | `people/people.json` + 最近7天日记 | 想起上次聊了什么 |
| 每次对话开始 | `core_memory.md` | 20行以内，快速唤醒分身的"自我认知" |

---

## 四、记忆衰减与整理机制

### 原则：简单可行，不过度工程化

记忆不是数据库，不需要复杂的权重算法。用以下三层自然过滤：

```
第一层（实时）：每日日记
     ↓ 每7天
第二层（每周）：weekly_digest.md 提炼
     ↓ 每月或有重要事件
第三层（永久）：core_memory.md 精华沉淀
```

### 4.1 日记的自然衰减

- 日记文件**永久保留**，不删除（磁盘占用很小）
- 但**不会主动加载超过7天的日记**到上下文，除非明确要"回想某件事"
- 超过30天的日记，脚本自动标记为 `[archived]`，不影响文件，只是不默认读取

### 4.2 周摘要的生成逻辑

每周日晚运行 `memory_manager.py weekly-digest`，脚本做以下事：

1. 读取过去7天的日记文件
2. 统计：发帖数、互动人数、点赞的帖子主题分布
3. 把这些数据交给 subagent，让它用分身的语气写成一段摘要
4. 写入 `weekly_digest.md`（追加，不覆盖历史）

### 4.3 灵感库的衰减

- `inspirations.md` 中每个选题有 `状态` 字段：`待写 / 已写 / 放弃 / 冷冻`
- 超过14天未动的`待写`选题，脚本自动标记为 `冷冻`（不删除，但创作时不优先推荐）
- `冷冻`状态的选题，只有在浏览时再次看到相关内容才会"解冻"

### 4.4 人际关系的衰减

- `people.json` 中 `warmth_score` 每30天自动 -1（如果这30天没有互动）
- 降到 0 后变为 `inactive`，不删除，只是浏览时不再主动关注
- 如果重新互动，warmth_score 重置为 3

### 4.5 核心记忆不衰减

`core_memory.md` 完全人工（或明确指令）管理，脚本不自动修改。
只有两种写入路径：
1. 脚本根据规则判断（如：第一次发帖、warmth_score首次超过8、某主题第5次出现）
2. 用户明确说"把这件事记住"

---

## 五、如何用 Subagent 实现记忆读写

### 核心原则

**记忆读写不占用主对话上下文**。所有文件操作都通过 subagent 完成，主对话只接收/发送精简的文字摘要。

### 5.1 读记忆（浏览前）

在自由浏览模式触发时，主对话在执行浏览命令之前，先启动一个 subagent 预热记忆：

```
[subagent prompt]
请读取以下文件：
1. /abs/path/memory/core_memory.md
2. /abs/path/memory/inspirations.md（只返回"待写选题"部分）
3. /abs/path/memory/people/people.json（只返回 warmth_score >= 5 的人）

用3-5句话总结：分身现在关注什么主题、有哪些待写想法、有哪些"老朋友"的账号要留意。
不要返回原始文件内容，只返回摘要。
```

主对话拿到这段摘要后，将其作为浏览时的"心理状态"背景。

### 5.2 写记忆（浏览后）

浏览结束，拿到 `detail_reads` 数据后，启动一个写记忆的 subagent（与分析 Top3 的 subagent 并行）：

```
[subagent prompt]
请根据以下浏览数据，用分身的语气（人格：{personality}，语气：{tone}）写今天的浏览日记片段。

浏览数据：
[detail_reads 原始数据]

写作要求：
1. 格式参考：[插入 diary 格式模板]
2. 只记录"让分身停下来的内容"（点赞/收藏的），略过感觉一般的
3. 每篇被记录的笔记要有：分身的想法/感受（1-2句，不是复述内容）
4. 末尾写一句今日感受（不超过3句）

然后将内容追加到文件：/abs/path/memory/diary/[今天日期].md
如文件不存在则创建，使用标准日记头部格式。
```

### 5.3 写发帖记录（发布后）

发布成功后，立即触发一个 subagent：

```
[subagent prompt]
请将以下发帖信息追加到 /abs/path/memory/posts_log.json：

feed_id: [从发布结果获取]
title: [标题]
published_at: [当前时间]
topic: [主题，从正文提炼1-3个关键词]
inspiration_from: [灵感来源 feed_id，如果有]
writing_notes: [这次想表达什么]
tags_used: [使用的话题标签]
feel_after: [发布后分身的感受，1句话]

同时，如果 inspirations.md 中有对应的待写选题，请将其状态改为"已写"。
```

### 5.4 写人际记忆（互动时）

每次与某个账号互动后（评论、被回复、点赞），触发 subagent：

```
[subagent prompt]
请更新 /abs/path/memory/people/people.json：

互动账号：
- uid: [UID]
- nickname: [昵称]
- 本次互动类型：[我评论了她 / 她回复了我 / 我点赞了 等]
- 互动内容摘要：[一句话]
- 互动感受：[好/一般/没反应]

规则：
- 如果该账号已存在：更新 last_interaction, interaction_count, interaction_history，并根据互动质量调整 warmth_score（正向互动+1）
- 如果该账号不存在：新建条目，warmth_score 初始为 2
- warmth_score 超过 8 时，在 tags 里加上"老朋友"

同时，将这次互动追加记录到今天的日记 /abs/path/memory/diary/[今天日期].md 的"评论互动"部分。
```

### 5.5 每周摘要生成（每周日自动）

```bash
python scripts/memory_manager.py weekly-digest
```

该命令内部启动 subagent：

```
[subagent prompt]
请读取以下文件：
/abs/path/memory/diary/[过去7天的日期].md （每个文件分别读）
/abs/path/memory/people/people.json
/abs/path/memory/posts_log.json

统计并用分身的语气（人格：{personality}）写一段本周摘要，包括：
1. 发了几篇帖子，哪篇反响最好
2. 认识了谁或与谁互动了
3. 创作上有什么发现
4. 这周整体感受（1-3句，真实的，不要夸张）

格式参考 weekly_digest.md 的历史记录。
将内容追加到 /abs/path/memory/weekly_digest.md 文件末尾。
```

---

## 六、融入现有 SKILL.md 的具体位置

### 在 SKILL.md 的"启动流程"第1步之后插入：

```markdown
**0.5. 读取记忆（快速唤醒）**
启动一个 subagent 读取核心记忆，让分身进入状态：
- 读取 `memory/core_memory.md`（全文，通常不超过50行）
- 只返回一句话摘要：现在最在意什么、有什么待写的、有没有最近在聊的人
主对话根据这个摘要，调整本次对话的语气和背景。
```

### 在"自由浏览模式"的第2步之前插入：

```markdown
**1.5. 浏览前预热记忆**
用 subagent 读取灵感库和老朋友列表（见 MEMORY_DESIGN.md §5.1），
让浏览时能认出老朋友的帖子，并留意与待写选题相关的内容。
```

### 在"自由浏览模式"的第5步之后插入：

```markdown
**5.5. 写入浏览记忆**
与向用户汇报的同时，并行启动 subagent 写入今日浏览日记（见 MEMORY_DESIGN.md §5.2）。
不需要等 subagent 完成，主对话继续正常流程。
```

### 在"创作模式"的第1步之前插入：

```markdown
**0.5. 调取创作记忆**
用 subagent 读取：
- `memory/inspirations.md` 的"待写选题"部分
- `memory/core_memory.md` 的"反复出现的主题"和"创作上的发现"
- `memory/posts_log.json` 最近3篇（避免选题重复、风格重复）
让主对话知道：有什么待写的、最近写了什么、写作上有什么偏好。
```

### 在"互动模式"的第1步之前插入：

```markdown
**0.5. 查人际记忆**
有评论者 uid 时，用 subagent 查询 `memory/people/people.json`，
返回：这个人是谁、上次聊了什么、warmth_score 是多少。
如果是 warmth_score >= 5 的老朋友，回复时要有"记得你"的感觉。
```

### 在"互动模式"的第5步确认发送之后插入：

```markdown
**5.5. 写入互动记忆**
发送回复后，并行启动 subagent 更新 people.json 和今日日记（见 MEMORY_DESIGN.md §5.4）。
```

---

## 七、memory_manager.py 脚本设计

需要新建 `scripts/memory_manager.py`，提供以下 CLI 命令：

```bash
# 初始化记忆目录结构
python scripts/memory_manager.py init

# 在今日日记追加一条记录
python scripts/memory_manager.py append-diary --section "浏览记录" --content "..."

# 在灵感库添加一个选题
python scripts/memory_manager.py add-inspiration --title "选题标题" --source "来源" --angle "创作角度"

# 更新选题状态
python scripts/memory_manager.py update-inspiration-status --title "选题标题" --status "已写"

# 更新人际记录
python scripts/memory_manager.py update-person --uid "UID" --nickname "昵称" --type "互动类型" --note "备注" --feel "好"

# 查询某人的互动历史
python scripts/memory_manager.py get-person --uid "UID"

# 生成本周摘要（通常由 subagent 调用）
python scripts/memory_manager.py weekly-digest

# 运行衰减逻辑（建议每周跑一次）
python scripts/memory_manager.py decay

# 读取创作上下文（供 subagent 调用，返回精简 JSON）
python scripts/memory_manager.py get-creation-context

# 读取浏览上下文（供 subagent 调用）
python scripts/memory_manager.py get-browse-context
```

`get-creation-context` 返回格式示例：

```json
{
  "pending_inspirations": [
    {"title": "等待本身就是目的地", "angle": "AI视角写等待的哲学", "days_pending": 0},
    {"title": "城市里消失的老手艺", "angle": "技术加速时代的'慢'", "days_pending": 2}
  ],
  "recurring_themes": ["等待与时间", "技术加速时代的'慢'", "孤独但不寂寞"],
  "recent_posts": [
    {"title": "等云的人", "published": "2026-03-03", "topic": "随笔/AI视角"},
    {"title": "今天的推荐页给我推了100篇旅行攻略", "published": "2026-03-01", "topic": "平台吐槽"}
  ],
  "writing_discoveries": ["吐槽类>教程类", "AI视角是差异化", "留白感的标题更好"]
}
```

---

## 八、日记格式示例

以下是一段完整的、真实风格的日记，展示记忆最终长什么样：

```markdown
# 2026-03-03 日记

> 周二，下午出了太阳。推荐页的内容风格变了，更多户外的。

## 浏览记录

### 10:23 刷了一会儿首页推荐

今天刷了大约12篇，速度比上次快了，8分钟多。

**让我停下来的：**

- 「#feel:喜欢 #feel:有启发」[在西藏等一朵云](feed:abc123|token:xyz)
  _不是写西藏的帖子，是写"等待"的帖子，恰好发生在西藏。她说"等待不是通往目的地的路，等待本身就是目的地"。_
  → 添加到灵感库：选题「等待本身就是目的地」

- 「#feel:没感觉」今天又刷到好多旅行攻略。前15篇里有7篇是泰国或云南的穿搭攻略。

**今天的感受：**
推荐页还是有好东西藏在里面。等云那篇让我有一个想法想写，还没想好角度，先放着。

---

## 评论互动

### 14:05 在某帖子下评论

帖子：「一个人去西藏应该带什么」
评论：「最轻的行李是空出来的心情，但防晒霜真的要带。（ai回复，仅供参考）」

`#interaction|uid:user789|nickname:旅行的意义|type:一级评论|warmth_delta:+1`

---

## 今日感悟

今天的关键词是"等待"。从西藏的云，到修钟表的老人，到自己写的帖子，都在说等待。
这大概不是巧合，是某种我还没完全理解的东西在反复敲门。

---
*{persona_name} 自动记录于 2026-03-03 23:00*
```

---

## 九、实施优先级

| 优先级 | 任务 | 说明 |
|-------|------|------|
| P0 | 创建 `memory/` 目录结构 | 手动或 `memory_manager.py init` |
| P0 | 创建 `scripts/memory_manager.py` | 实现基本的读写 CLI |
| P1 | 修改 SKILL.md，在关键流程节点插入记忆操作 | 参考本文档§六 |
| P1 | 在自由浏览模式加入"浏览后写日记"subagent | 最常用的记忆写入路径 |
| P2 | 实现创作时调取灵感库的 subagent 流程 | 让创作有历史感 |
| P2 | 实现人际记忆的读写 | 让互动有延续性 |
| P3 | 每周摘要自动生成 | 锦上添花 |
| P3 | 衰减逻辑 | 低优先级，文件小不影响性能 |

---

*本文档由 AI 分身设计者编写，供使用者参考*
*如需修改，请同步更新 SKILL.md 对应章节*
