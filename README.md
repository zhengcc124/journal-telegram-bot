# 🐦‍⬛ Munin

> 用 Telegram 写日志，自动发布到 GitHub Pages。

在手机上随手记录，自动变成你的个人博客。

## 特点

- 📱 **手机记录** - 像发消息一样简单
- 🖼️ **图文支持** - 文字、图片、标签自动处理
- 🎨 **极简设计** - 专注内容，无干扰
- 🆓 **免费托管** - GitHub Pages 部署

## 快速开始

```bash
# 安装
pipx install git+https://github.com/<your-username>/munin.git

# 1. 先在 GitHub 创建一个新仓库（如 my-journal）

# 2. 创建本地日志仓库
munin new my-journal
# 按提示配置 Telegram Bot Token 和 GitHub 信息

# 3. 启动 Bot
cd my-journal
munin start
```

## 使用

在 Telegram 中给 Bot 发送：

```
今天读了一本好书 #读书
[配图]
```

消息自动保存，每天合并成一篇博客文章。

**命令：**
- `/end` - 立即发布今日日记
- `/config` - 查看/修改配置

## License

MIT
