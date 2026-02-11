# 📝 Enlighten — 用 Telegram 写日志，用 GitHub 发布博客

> 在手机上随手记录，自动变成你的个人博客文章。

## 背景：为什么做这个项目？

很多人都想养成写日志的习惯，但现有的方案总有各种摩擦：

- **传统博客（WordPress / Hugo）**：每次写文章都要打开电脑，进后台，排版发布——流程太重，不适合碎片化记录。
- **笔记类 App（Notion / Obsidian）**：内容锁在 App 里，不方便公开分享，也没有独立博客的"拥有感"。
- **社交媒体（Twitter / 微博）**：内容不属于你，平台可能审查或消失。
- **Apple Journal**：没有公开 API，内容无法导出。

**核心矛盾**：我们想要"像发微信一样简单地记录"，同时又想要"拥有一个属于自己的博客网站"。

Enlighten 就是为了解决这个矛盾而生的。

## 它能做什么？

**一句话概括**：在 Telegram 里发消息（文字 / 图片），自动变成你 GitHub Pages 博客上的一篇文章。

具体来说：

1. 📱 你在手机上打开 Telegram，给 Bot 发一条消息
2. 🤖 Bot 收到消息，创建一个 GitHub Issue（图片会自动上传到仓库）
3. ⚙️ GitHub Actions 检测到新 Issue，自动将其转换为 Markdown 文件
4. 🌐 GitHub Pages 部署更新，你的博客上就多了一篇新文章

**整个过程不到 1 分钟，你只需要动动手指发条消息。**

## 优势

| 对比维度 | 传统博客 | 本项目 |
|---------|---------|-------|
| 发布流程 | 打开电脑 → 编辑器 → 排版 → 发布 | 手机发条 Telegram 消息 |
| 图片处理 | 手动上传、压缩、插入链接 | 直接发图，自动处理 |
| 服务器成本 | 需要服务器或付费托管 | GitHub Pages 免费 |
| 数据所有权 | 取决于平台 | 所有内容在你的 GitHub 仓库 |
| 部署复杂度 | 中到高 | 一次配置，永久使用 |
| 移动端体验 | 差（大多数后台不适配手机） | 原生 Telegram 体验 |

## 系统架构

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│             │     │                  │     │              │     │              │
│  Telegram   │────▶│  Telegram Bot    │────▶│  GitHub      │────▶│  GitHub      │
│  (手机端)    │     │  (Mac mini)      │     │  Issue       │     │  Actions     │
│             │     │                  │     │              │     │              │
└─────────────┘     └──────────────────┘     └──────┬───────┘     └──────┬───────┘
                                                    │                    │
                     用户发消息          Bot 创建 Issue          Actions 转 Markdown
                     文字 / 图片         上传图片到仓库          关闭 Issue
                                                                 打 published 标签
                                                                        │
                                                                        ▼
                                                              ┌──────────────┐
                                                              │              │
                                                              │  GitHub      │
                                                              │  Pages       │
                                                              │  (博客网站)   │
                                                              │              │
                                                              └──────────────┘
```

### 数据流详解

```
用户发 Telegram 消息
        │
        ▼
Bot 接收消息 (Long Polling)
        │
        ├── 文本消息：提取 #标签，构建 Issue 内容
        │
        ├── 图片消息：
        │   ├── 下载图片
        │   ├── 上传到仓库 content/images/YYYY/MM/DD/
        │   └── 在 Issue 中插入 Markdown 图片引用
        │
        ▼
创建 GitHub Issue（带 journal 标签）
        │
        ▼
GitHub Actions 被触发（on: issues labeled）
        │
        ├── 读取 Issue 内容
        ├── 生成 frontmatter（title, date, tags）
        ├── 写入 content/posts/YYYY/MM/DD/HH-MM-SS.md
        ├── git commit & push
        ├── 给 Issue 打上 published 标签
        └── 关闭 Issue
        │
        ▼
GitHub Pages 自动部署（如果已配置）
```

## 项目结构

```
journal-telegram-bot/
│
├── bot/                          # Telegram Bot（运行在 Mac mini 上）
│   ├── __init__.py
│   ├── config.py                 # 集中配置管理：从 .env 加载所有配置
│   ├── github_client.py          # GitHub API 封装：创建 Issue、上传文件
│   ├── handlers.py               # 消息处理器：解析文本/图片、提取标签
│   └── main.py                   # 入口：初始化 Bot，注册处理器，启动轮询
│
├── scripts/
│   └── issue_to_md.py            # Issue → Markdown 转换脚本（GitHub Actions 调用）
│
├── .github/
│   └── workflows/
│       └── publish.yml           # GitHub Actions 工作流定义
│
├── macos/                        # macOS 部署相关
│   ├── run.sh                    # 启动脚本
│   └── com.journal.bot.plist     # launchd 守护进程配置
│
├── .env.example                  # 环境变量模板
├── .gitignore
├── requirements.txt
└── README.md
```

### 各模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **配置管理** | `bot/config.py` | 从 `.env` 加载配置，校验必填项，提供默认值。不可变 dataclass，一次加载全局使用 |
| **GitHub 客户端** | `bot/github_client.py` | 封装 GitHub REST API：创建 Issue、上传文件（Base64）、管理标签、关闭 Issue |
| **消息处理** | `bot/handlers.py` | 处理 Telegram 消息：文本提取 `#标签`、图片下载上传、构建 Issue 标题和正文 |
| **Bot 入口** | `bot/main.py` | 初始化各组件，注册 `/start` `/help` 命令和消息处理器，启动 Long Polling |
| **Issue 转换** | `scripts/issue_to_md.py` | 被 GitHub Actions 调用：读 Issue → 生成 YAML frontmatter → 写 Markdown 文件 → 关闭 Issue |
| **CI/CD** | `.github/workflows/publish.yml` | 监听 Issue 事件，触发转换脚本，commit 并 push 生成的文章 |

## 快速开始

### 前置条件

- Python 3.11+
- 一台常开的机器（Mac mini / 服务器 / 任何能跑 Python 的设备）
- Telegram 账号
- GitHub 账号

### 第一步：创建 Telegram Bot

1. 在 Telegram 中搜索 **@BotFather**，发送 `/newbot`
2. 按提示输入 Bot 名称和用户名
3. 记下返回的 **Bot Token**（形如 `123456:ABC-DEF...`）
4. 给 Bot 发一条消息，然后访问 `https://api.telegram.org/bot<你的Token>/getUpdates`，找到你的 **User ID**（`message.from.id` 字段）

### 第二步：创建 GitHub 仓库

1. 在 GitHub 上创建一个**新的公开仓库**（比如叫 `my-journal`）
2. 创建一个 **Personal Access Token**：
   - 进入 GitHub → Settings → Developer settings → Personal access tokens → **Tokens (classic)**
   - 点击 **Generate new token (classic)**
   - 勾选权限：`repo`（完整仓库访问权限）
   - 生成并记下 Token
3. 在仓库中创建两个目录（也可以让 Bot 自动创建）：
   - `content/posts/` — 存放文章
   - `content/images/` — 存放图片

### 第三步：配置 GitHub Actions

把本项目中的以下文件复制到你的 `my-journal` 仓库：

```
my-journal/
├── scripts/
│   └── issue_to_md.py        # 从本项目复制
└── .github/
    └── workflows/
        └── publish.yml        # 从本项目复制
```

> **注意**：`publish.yml` 中的环境变量需要和你的 `.env` 保持一致（如 `ARTICLE_DIR`、`JOURNAL_LABEL` 等）。

### 第四步：部署 Bot

```bash
# 克隆项目
git clone https://github.com/你的用户名/journal-telegram-bot.git
cd journal-telegram-bot

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 Token 和仓库信息
```

编辑 `.env` 文件：

```bash
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...        # 第一步拿到的 Bot Token
ALLOWED_USER_IDS=你的UserID                   # 第一步拿到的 User ID
GITHUB_TOKEN=ghp_xxxx                        # 第二步拿到的 PAT
GITHUB_OWNER=你的GitHub用户名
GITHUB_REPO=my-journal
```

### 第五步：启动 Bot

```bash
# 手动启动（测试用）
python -m bot.main

# 看到 "🚀 Bot 启动中..." 就说明成功了
```

### 第六步：试一试！

在 Telegram 中找到你的 Bot，发送：

```
今天天气真好 #生活 #随想
```

几秒后你会收到确认回复，然后去 GitHub 仓库看看，Issue 和 Markdown 文件都自动生成了 🎉

## macOS 后台运行（launchd）

测试通过后，配置 launchd 让 Bot 开机自启、崩溃自动重启：

```bash
# 1. 创建日志目录
mkdir -p ~/path/to/journal-telegram-bot/logs

# 2. 编辑 plist 文件，把路径替换成你的实际路径
vim macos/com.journal.bot.plist

# 3. 复制到 LaunchAgents
cp macos/com.journal.bot.plist ~/Library/LaunchAgents/

# 4. 加载并启动
launchctl load ~/Library/LaunchAgents/com.journal.bot.plist

# 5. 查看状态
launchctl list | grep journal
```

**常用 launchd 命令**：

```bash
# 停止
launchctl unload ~/Library/LaunchAgents/com.journal.bot.plist

# 重启（先 unload 再 load）
launchctl unload ~/Library/LaunchAgents/com.journal.bot.plist
launchctl load ~/Library/LaunchAgents/com.journal.bot.plist

# 查看日志
tail -f ~/path/to/journal-telegram-bot/logs/bot.log
```

## 配置 GitHub Pages（可选）

如果你想让生成的 Markdown 文件自动部署为网站：

1. 进入仓库 **Settings → Pages**
2. Source 选择 **GitHub Actions** 或者 **Deploy from a branch**（选 `main` 分支）
3. 如果需要自定义域名，在 Custom domain 中填写

你也可以在仓库里加一个静态站点生成器（如 Hugo / Astro / VitePress）来美化页面，`content/posts/` 下的 Markdown 文件会自动作为文章源。

## 设计要点与实现难点

### 1. 为什么选 Telegram Bot 而不是微信 / 其他？

Telegram Bot API 是完全开放的，不需要企业认证、不需要服务器公网 IP（Long Polling 模式下），也不需要审核。微信公众号 / 小程序都有各种限制，不适合个人项目。

### 2. 为什么用 GitHub Issue 做中转？

直接让 Bot commit 文件到仓库当然可以，但用 Issue 做中转有几个好处：

- **解耦**：Bot 只负责"收消息 → 创建 Issue"，转换逻辑在 Actions 里，两边可以独立迭代
- **可追溯**：每条日志对应一个 Issue，有完整的创建时间、标签、讨论记录
- **可补救**：如果转换出错，Issue 还在，可以手动重新触发
- **天然的 CMS**：GitHub Issue 界面本身就是一个不错的内容管理后台

### 3. Long Polling vs Webhook

Webhook 需要一个公网可访问的 HTTPS 端点，对于跑在家里 Mac mini 上的场景不太方便（需要内网穿透或者 Cloudflare Tunnel）。Long Polling 虽然不如 Webhook "优雅"，但胜在简单——不需要任何网络配置，只要能访问外网就行。

### 4. 图片处理流程

这是实现中最复杂的部分：

1. Telegram 发送图片时会生成多个不同分辨率的版本，我们取最大的那个
2. 通过 Telegram Bot API 下载图片二进制数据
3. 通过 GitHub Contents API 上传到仓库（Base64 编码）
4. 生成 Markdown 图片引用，插入到 Issue 正文中

### 5. 标签系统

用户在消息中使用 `#标签` 语法（如 `#读书 #思考`），Bot 会：

- 用正则提取所有 `#标签`（支持中文）
- 将标签作为 GitHub Issue 的 Labels
- 在 Markdown frontmatter 中生成 `tags` 字段
- `journal` 和 `published` 是系统标签，不会出现在文章的 tags 中

### 6. 时区处理

GitHub API 返回的时间是 UTC，但日志的目录结构（`YYYY/MM/DD/`）应该按用户所在时区来组织。通过 `JOURNAL_TZ` 环境变量配置时区（默认 `Asia/Shanghai`），使用 Python 3.9+ 内置的 `zoneinfo` 模块处理转换。

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|-------|------|-------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | - | Telegram Bot Token |
| `ALLOWED_USER_IDS` | ❌ | 空（不限制） | 允许使用的 Telegram 用户 ID，逗号分隔 |
| `GITHUB_TOKEN` | ✅ | - | GitHub Personal Access Token |
| `GITHUB_OWNER` | ✅ | - | GitHub 用户名或组织名 |
| `GITHUB_REPO` | ✅ | - | 仓库名 |
| `GITHUB_BRANCH` | ❌ | `main` | 分支名 |
| `ARTICLE_DIR` | ❌ | `content/posts` | Markdown 文章存放目录 |
| `IMAGE_DIR` | ❌ | `content/images` | 图片存放目录 |
| `JOURNAL_LABEL` | ❌ | `journal` | 触发转换的 Issue 标签 |
| `PUBLISHED_LABEL` | ❌ | `published` | 处理完成后的标签 |
| `JOURNAL_TZ` | ❌ | `Asia/Shanghai` | 时区 |

## 生成的文章格式

每篇文章的 Markdown 文件结构如下：

```markdown
---
title: 今天天气真好
date: '2026-02-11T15:30:00+08:00'
tags:
- 生活
- 随想
github_issue: 42
github_url: https://github.com/user/repo/issues/42
---

今天天气真好 #生活 #随想

---

![](content/images/2026/02/11/photo_153000_abcd1234.jpg)
```

文件路径：`content/posts/2026/02/11/15-30-00.md`

## FAQ

**Q: Bot 挂了怎么办？**
A: 如果配置了 launchd，它会自动重启。Issue 不会丢失，重启后 Bot 继续工作。

**Q: 一天发多条消息会冲突吗？**
A: 不会。每条消息生成独立的 Issue，文件名精确到秒（`HH-MM-SS.md`）。

**Q: 可以用私有仓库吗？**
A: 可以，但 GitHub Pages 在私有仓库上需要 GitHub Pro。Bot 和 Actions 的功能不受影响。

**Q: 支持发视频 / 文件吗？**
A: 当前版本只支持文字和图片。视频和文件支持可以后续扩展。

**Q: 能不能不用 Mac mini，部署到服务器上？**
A: 完全可以。Bot 就是一个普通的 Python 进程，跑在任何 Linux / macOS 机器上都行，用 `systemd`、`supervisor` 或 Docker 管理都可以。

## License

MIT
