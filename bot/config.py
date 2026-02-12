"""
集中配置管理

从环境变量 / .env 文件加载所有配置项，
并提供校验与默认值。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def _require(name: str) -> str:
    """读取必填环境变量，缺失时直接退出并给出提示。"""
    val = os.getenv(name, "").strip()
    if not val:
        print(f"[ERROR] 缺少必填环境变量: {name}，请检查 .env 文件。")
        sys.exit(1)
    return val


@dataclass(frozen=True)
class Config:
    """不可变配置对象，一次加载、全局使用。"""

    # ── Telegram ─────────────────────────────────────────
    telegram_token: str
    allowed_user_ids: list[int]          # 白名单，只允许这些用户发消息

    # ── GitHub ───────────────────────────────────────────
    github_token: str
    github_owner: str                    # 仓库 owner（用户名 / 组织名）
    github_repo: str                     # 仓库名

    # ── 行为 ─────────────────────────────────────────────
    branch: str = "main"
    article_dir: str = "content/posts"   # Markdown 存放根目录
    image_dir: str = "content/images"    # 图片存放根目录
    journal_label: str = "journal"       # 标识日志类 Issue 的标签
    published_label: str = "published"   # 处理完成后打上的标签
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"))
    
    # ── 日记格式 ──────────────────────────────────────────
    show_entry_time: bool = True         # 是否显示条目时间
    entry_time_format: str = "%H:%M"     # 时间格式

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "Config":
        """从 .env 文件 + 环境变量构建 Config 实例。"""
        if env_path:
            load_dotenv(env_path, override=True)
        else:
            # 优先级:
            # 1. 当前目录 .munin/.env (仓库本地配置)
            # 2. 当前目录 .env (本地调试)
            # 3. 项目根目录 .env (源码运行)
            # 4. ~/.munin/.env (历史兼容)

            project_root = Path(__file__).resolve().parent.parent
            cwd_repo_config = Path.cwd() / ".munin" / ".env"
            user_legacy_config = Path.home() / ".munin" / ".env"

            candidates = [
                cwd_repo_config,
                Path.cwd() / ".env",
                project_root / ".env",
                user_legacy_config,
            ]

            for candidate in candidates:
                if candidate.exists():
                    load_dotenv(candidate, override=True)
                    break

        # 白名单：逗号分隔的数字
        raw_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
        allowed = [int(x.strip()) for x in raw_ids.split(",") if x.strip()] if raw_ids else []

        # 时区
        tz_name = os.getenv("JOURNAL_TZ", "Asia/Shanghai").strip()
        try:
            tz = ZoneInfo(tz_name)
        except KeyError:
            print(f"[WARN] 无法识别时区 '{tz_name}'，回退到 Asia/Shanghai")
            tz = ZoneInfo("Asia/Shanghai")

        return cls(
            telegram_token=_require("TELEGRAM_BOT_TOKEN"),
            allowed_user_ids=allowed,
            github_token=_require("GITHUB_TOKEN"),
            github_owner=_require("GITHUB_OWNER"),
            github_repo=_require("GITHUB_REPO"),
            branch=os.getenv("GITHUB_BRANCH", "main").strip(),
            article_dir=os.getenv("ARTICLE_DIR", "content/posts").strip(),
            image_dir=os.getenv("IMAGE_DIR", "content/images").strip(),
            journal_label=os.getenv("JOURNAL_LABEL", "journal").strip(),
            published_label=os.getenv("PUBLISHED_LABEL", "published").strip(),
            timezone=tz,
        )
