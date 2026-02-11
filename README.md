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
| 部署复杂度 | 中到高 | **极简 CLI 工具，一行命令启动** |
| 移动端体验 | 差（大多数后台不适配手机） | 原生 Telegram 体验 |

## 系统架构

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│             │     │                  │     │              │     │              │
│  Telegram   │────▶│  Munin Bot       │────▶│  GitHub      │────▶│  GitHub      │
│  (手机端)    │     │  (本地/服务器)    │     │  Issue       │     │  Actions     │
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

> **Munin**（穆宁）——北欧神话中奥丁的渡鸦，名字意为"记忆"。它每天飞出去收集世间的信息，再带回给主人。就像这个 Bot 帮你收集日志、投递到 GitHub 一样。

## 快速开始

### 前置条件

- Python 3.11+
- 一台常开的机器（Mac mini / 服务器 / 树莓派）
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

### 第三步：初始化日志仓库（自动化）

你不需要手动复制 workflow 和脚本了，`munin` 会自动写入：

- `.github/workflows/publish.yml`
- `scripts/issue_to_md.py`
- `.munin/.env`（仓库私有配置）
- `.gitignore` 中自动追加 `.munin/`（避免敏感配置入库）

### 第四步：安装与运行 Bot（客户端）

#### 1. 安装

```bash
# 推荐：使用 pipx 安装到隔离环境（无需手动管理虚拟环境）
pipx install git+https://github.com/zhengcc124/journal-telegram-bot.git

# 或者：开发者模式（源码运行）
git clone https://github.com/zhengcc124/journal-telegram-bot.git
cd journal-telegram-bot
pip install -e .
```

#### 2. 创建并配置日志仓库

在你希望放置日志仓库的目录下运行：

```bash
munin new my-journal
```

它会：

1. 创建 `my-journal/` 目录（若不存在）
2. 交互式收集 Telegram/GitHub 配置
3. 输入 GitHub 仓库地址（HTTPS/SSH，都支持，必填）
4. 写入仓库配置到 `my-journal/.munin/.env`
5. 自动写入 workflow + 转换脚本
6. 执行 `git init` 并自动提交一次初始化 commit
7. 自动尝试 `git remote add origin` + 首次 `git push`

如果仓库已经存在，只想重配当前仓库参数：

```bash
cd my-journal
munin config
```

> 如果你还没在 GitHub 创建远端仓库，`munin` 会明确提示并给出可直接执行的 `git` 命令。

#### 3. 启动 Bot（在仓库目录内）

```bash
cd my-journal
```

```bash
# 前台启动（适合测试，按 Ctrl+C 停止）
munin start

# 后台启动（Daemon 模式，适合长期运行）
munin start --daemon
```

#### 4. 管理 Bot

```bash
# 查看运行状态
munin status

# 查看实时日志
munin logs

# 停止后台 Bot
munin stop
```

### 第五步：试一试！

在 Telegram 中找到你的 Bot，发送：

```
今天天气真好 #生活 #随想
```

几秒后你会收到确认回复，然后去 GitHub 仓库看看，Issue 和 Markdown 文件都自动生成了 🎉

## 常用命令参考

```bash
$ munin --help

Commands:
  new     创建并初始化日志仓库
  config  配置当前仓库（.munin/.env）
  start   启动 Bot (支持 --daemon)
  stop    停止当前仓库后台运行的 Bot
  status  查看运行状态
  logs    查看当前仓库日志 (tail -f 效果)
```

## macOS 开机自启 (可选)

虽然 `munin start --daemon` 可以后台运行，但重启电脑后需要手动执行。如果你希望开机自启，可以使用 `launchd`。

1. 找到 `munin` 的路径：
   ```bash
   which munin
   # 例如输出：/Users/yourname/.local/bin/munin
   ```

2. 修改 `macos/com.journal.bot.plist`，将程序路径替换为上面的输出，参数改为 `start`。

3. 加载 plist：
   ```bash
   cp macos/com.journal.bot.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.journal.bot.plist
   ```

## 环境变量说明

配置保存在每个日志仓库自己的 `.munin/.env` 中（例如 `my-journal/.munin/.env`），支持以下选项：

| 变量名 | 必填 | 说明 |
|-------|------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram Bot Token |
| `ALLOWED_USER_IDS` | ❌ | 允许使用的 Telegram 用户 ID，逗号分隔 |
| `GITHUB_TOKEN` | ✅ | GitHub Personal Access Token |
| `GITHUB_OWNER` | ✅ | GitHub 用户名或组织名 |
| `GITHUB_REPO` | ✅ | 仓库名 |
| `GITHUB_REPO_URL` | ✅ | 仓库地址（支持 HTTPS/SSH，用于自动推送） |
| `GITHUB_BRANCH` | ❌ | 分支名 (默认 main) |
| `ARTICLE_DIR` | ❌ | Markdown 文章存放目录 |
| `IMAGE_DIR` | ❌ | 图片存放目录 |
| `JOURNAL_LABEL` | ❌ | 日志 Issue 标签（默认 `journal`） |
| `PUBLISHED_LABEL` | ❌ | 发布完成后标签（默认 `published`） |
| `JOURNAL_TZ` | ❌ | 时区 (默认 Asia/Shanghai) |

## 多仓库与 Token 约束

- 推荐关系：`1 Telegram Bot Token ↔ 1 日志仓库`
- 本机会做 Token 运行冲突检查：同一个 Token 不能同时被两个仓库进程启动
- 这个检查是本机级别；如果你在另一台机器也启动了同一个 Token，Telegram 仍可能出现轮询冲突

## License

MIT
