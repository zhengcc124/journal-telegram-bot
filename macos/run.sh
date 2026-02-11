#!/bin/bash

# 启动脚本：用于手动启动或 launchd 调用

set -e

# 进入项目目录
cd "$(dirname "$0")/.."

# 加载虚拟环境（如果使用）
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 启动 Bot
exec python -m bot.main
