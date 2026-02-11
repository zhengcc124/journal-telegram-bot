import os
import sys
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

# 尝试导入 psutil，如果不存在则报错（虽然在依赖里，但防止环境问题）
try:
    import psutil
except ImportError:
    psutil = None

# 定义常量
APP_NAME = "munin"
APP_DIR = Path.home() / f".{APP_NAME}"
ENV_FILE = APP_DIR / ".env"
PID_FILE = APP_DIR / "bot.pid"
LOG_FILE = APP_DIR / "bot.log"

app = typer.Typer(help="Munin — 记忆之鸦，你的 Telegram 日志机器人")
console = Console()


def _check_running() -> Optional[int]:
    """检查 Bot 是否正在运行，返回 PID 或 None"""
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
        if psutil and psutil.pid_exists(pid):
            return pid
        elif not psutil:
            # Fallback for when psutil is not available (Unix only)
            try:
                os.kill(pid, 0)
                return pid
            except OSError:
                pass
    except (ValueError, ProcessLookupError):
        pass

    return None


@app.command()
def init(force: bool = typer.Option(False, "--force", "-f", help="强制覆盖现有配置")):
    """
    初始化配置向导
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)

    if ENV_FILE.exists() and not force:
        console.print(f"[yellow]配置文件已存在: {ENV_FILE}[/yellow]")
        if not Confirm.ask("是否覆盖现有配置?"):
            raise typer.Exit()

    console.print(Panel.fit("欢迎使用 Munin 配置向导", style="bold green"))

    # 交互式获取配置
    tg_token = Prompt.ask("🤖 Telegram Bot Token")

    allowed_users = Prompt.ask(
        "👤 允许的用户 ID (逗号分隔，可选)",
        default=""
    )

    gh_token = Prompt.ask("🔑 GitHub Personal Access Token (Repo 权限)")
    gh_owner = Prompt.ask("👤 GitHub 用户名/组织名")
    gh_repo = Prompt.ask("📦 GitHub 仓库名")

    # 高级配置
    console.print("\n[bold]以下是可选的高级配置 (按回车使用默认值)[/bold]")
    branch = Prompt.ask("🌿 分支名", default="main")
    article_dir = Prompt.ask("📂 文章存放目录", default="content/posts")
    image_dir = Prompt.ask("🖼️ 图片存放目录", default="content/images")

    # 生成 .env 内容
    env_content = f"""# Journal Bot Configuration
TELEGRAM_BOT_TOKEN={tg_token}
ALLOWED_USER_IDS={allowed_users}
GITHUB_TOKEN={gh_token}
GITHUB_OWNER={gh_owner}
GITHUB_REPO={gh_repo}
GITHUB_BRANCH={branch}
ARTICLE_DIR={article_dir}
IMAGE_DIR={image_dir}
JOURNAL_TZ=Asia/Shanghai
"""

    ENV_FILE.write_text(env_content)
    console.print(f"\n[bold green]✅ 配置已保存至: {ENV_FILE}[/bold green]")
    console.print("你可以随时通过 `munin start` 启动机器人")


@app.command()
def start(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="在后台运行 (Daemon 模式)"),
    restart: bool = typer.Option(False, "--restart", "-r", help="如果已运行，先停止再启动")
):
    """
    启动 Bot
    """
    # 检查配置
    if not ENV_FILE.exists():
        console.print("[red]❌ 未找到配置文件[/red]")
        console.print("请先运行: [bold]munin init[/bold]")
        raise typer.Exit(1)

    # 检查是否已运行
    pid = _check_running()
    if pid:
        if restart:
            stop()
            time.sleep(1) # 等待进程清理
        else:
            console.print(f"[yellow]Bot 已经在运行中 (PID: {pid})[/yellow]")
            console.print("使用 [bold]munin stop[/bold] 停止，或 [bold]--restart[/bold] 重启")
            raise typer.Exit()

    if daemon:
        console.print("🚀 正在后台启动 Bot...")

        # 准备日志文件
        log_f = open(LOG_FILE, "a")

        # 启动子进程
        # 注意: 这里使用 sys.executable 确保使用相同的 Python 环境
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "bot.main"],
                cwd=APP_DIR,  # 确保 cwd 设置正确，或者让 main 自动找配置
                stdout=log_f,
                stderr=log_f,
                start_new_session=True  # 也就是 setsid，脱离当前终端
            )

            # 写入 PID
            PID_FILE.write_text(str(proc.pid))

            console.print(f"[bold green]✅ Bot 已在后台启动 (PID: {proc.pid})[/bold green]")
            console.print(f"📄 日志文件: {LOG_FILE}")
            console.print("使用 [bold]munin logs[/bold] 查看实时日志")

        except Exception as e:
            console.print(f"[red]启动失败: {e}[/red]")
            raise typer.Exit(1)

    else:
        # 前台运行
        console.print("[bold green]🚀 正在前台启动 Bot (按 Ctrl+C 停止)...[/bold green]")
        # 这里需要导入 main 并运行
        # 为了确保环境变量能正确加载，我们手动 load 一下 user config
        # 虽然 config.py 会处理，但为了保险起见（或者如果 main 里有其他依赖 env 的逻辑）
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)

        from bot.main import main
        try:
            main()
        except KeyboardInterrupt:
            console.print("\n[yellow]Bot 已停止[/yellow]")


@app.command()
def stop():
    """
    停止后台运行的 Bot
    """
    pid = _check_running()
    if not pid:
        console.print("[yellow]没有发现运行中的 Bot[/yellow]")
        return

    try:
        console.print(f"正在停止 PID {pid}...")
        os.kill(pid, signal.SIGTERM)

        # 等待进程结束
        for _ in range(50):
            if not _check_running():
                break
            time.sleep(0.1)

        if _check_running():
            console.print("[red]停止失败，尝试强制停止...[/red]")
            os.kill(pid, signal.SIGKILL)

        console.print(f"[green]✅ Bot (PID {pid}) 已停止[/green]")

    except ProcessLookupError:
        console.print("[yellow]进程已不存在[/yellow]")
    except Exception as e:
        console.print(f"[red]停止出错: {e}[/red]")
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


@app.command()
def status():
    """
    查看运行状态
    """
    pid = _check_running()

    table = f"""
    [bold]状态检查[/bold]

    配置路径: {ENV_FILE} ({"✅ 存在" if ENV_FILE.exists() else "❌ 不存在"})
    日志路径: {LOG_FILE}
    运行状态: {"🟢 运行中" if pid else "⚪️ 未运行"}
    PID: {pid if pid else "-"}
    """
    console.print(Panel(table.strip(), title="Munin Status", expand=False))


@app.command()
def logs(lines: int = typer.Option(20, "--lines", "-n", help="显示最后 N 行")):
    """
    查看日志 (tail -f 效果)
    """
    if not LOG_FILE.exists():
        console.print("[yellow]日志文件不存在[/yellow]")
        return

    console.print(f"[bold]显示最后 {lines} 行日志 (Ctrl+C 退出):[/bold]")

    # 使用 tail 命令 (简单有效)
    try:
        subprocess.run(["tail", "-f", "-n", str(lines), str(LOG_FILE)])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    app()
