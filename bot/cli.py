from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from dotenv import dotenv_values
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "munin"
GLOBAL_DIR = Path.home() / f".{APP_NAME}"
RUNTIME_DIR = GLOBAL_DIR / "runtime"
TOKEN_LOCK_DIR = RUNTIME_DIR / "token_locks"
PROC_META_DIR = RUNTIME_DIR / "procs"

MUNIN_SOURCE_REPO_RAW_BASE = os.getenv(
    "MUNIN_SOURCE_REPO_RAW_BASE",
    "https://raw.githubusercontent.com/zhengcc124/journal-telegram-bot/refs/heads/main",
).rstrip("/")
PUBLISH_WORKFLOW_SOURCE_URL = f"{MUNIN_SOURCE_REPO_RAW_BASE}/.github/workflows/publish.yml"
ISSUE_TO_MD_SOURCE_URL = f"{MUNIN_SOURCE_REPO_RAW_BASE}/scripts/issue_to_md.py"

app = typer.Typer(help="Munin — 记忆之鸦，你的 Telegram 日志机器人")
console = Console()


def _repo_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = (repo_root or Path.cwd()).resolve()
    munin_dir = root / ".munin"
    return {
        "root": root,
        "munin_dir": munin_dir,
        "env": munin_dir / ".env",
        "pid": munin_dir / "bot.pid",
        "log": munin_dir / "bot.log",
    }


def _ensure_runtime_dirs() -> None:
    TOKEN_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    PROC_META_DIR.mkdir(parents=True, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if psutil:
        return psutil.pid_exists(pid)

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _check_running(pid_file: Path) -> Optional[int]:
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None

    return pid if _pid_alive(pid) else None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_lock_path(token_hash: str) -> Path:
    return TOKEN_LOCK_DIR / f"{token_hash}.json"


def _proc_meta_path(pid: int) -> Path:
    return PROC_META_DIR / f"{pid}.json"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_token_lock(token_hash: str, repo_root: Path, pid: int, state: str) -> None:
    _write_json(
        _token_lock_path(token_hash),
        {
            "token_hash": token_hash,
            "repo_path": str(repo_root),
            "pid": pid,
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _cleanup_stale_token_lock(token_hash: str) -> None:
    lock_path = _token_lock_path(token_hash)
    data = _load_json(lock_path)
    if not data:
        if lock_path.exists():
            lock_path.unlink(missing_ok=True)
        return

    pid = int(data.get("pid", 0) or 0)
    if not _pid_alive(pid):
        lock_path.unlink(missing_ok=True)


def _acquire_token_lock(token: str, repo_root: Path, pid: int, state: str) -> str:
    _ensure_runtime_dirs()
    token_hash = _hash_token(token)
    lock_path = _token_lock_path(token_hash)

    _cleanup_stale_token_lock(token_hash)

    if lock_path.exists():
        data = _load_json(lock_path) or {}
        holder_pid = int(data.get("pid", 0) or 0)
        holder_repo = data.get("repo_path", "未知仓库")
        raise RuntimeError(
            f"该 Telegram Bot Token 已在本机被占用 (PID: {holder_pid}, Repo: {holder_repo})"
        )

    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("该 Telegram Bot Token 正在被本机其他进程启动")

    with os.fdopen(fd, "w", encoding="utf-8") as f:
        payload = {
            "token_hash": token_hash,
            "repo_path": str(repo_root),
            "pid": pid,
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    return token_hash


def _release_token_lock(
    token_hash: str,
    expected_repo: Path | None = None,
    expected_pid: int | None = None,
) -> None:
    lock_path = _token_lock_path(token_hash)
    if not lock_path.exists():
        return

    data = _load_json(lock_path) or {}
    if expected_repo is not None:
        holder_repo = Path(str(data.get("repo_path", ""))).resolve()
        if holder_repo != expected_repo.resolve():
            return

    if expected_pid is not None:
        holder_pid = int(data.get("pid", 0) or 0)
        if holder_pid != expected_pid:
            return

    lock_path.unlink(missing_ok=True)


def _write_proc_meta(pid: int, repo_root: Path, token_hash: str, log_file: Path) -> None:
    _write_json(
        _proc_meta_path(pid),
        {
            "pid": pid,
            "repo_path": str(repo_root),
            "token_hash": token_hash,
            "log_file": str(log_file),
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _remove_proc_meta(pid: int) -> None:
    _proc_meta_path(pid).unlink(missing_ok=True)


def _download_text_via_curl_or_wget(url: str) -> str:
    commands = [
        ["curl", "-fsSL", url],
        ["wget", "-qO-", url],
    ]

    errors: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            errors.append(f"{cmd[0]} not found")
            continue

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout

        stderr = (result.stderr or "").strip()
        errors.append(f"{cmd[0]} failed: {stderr or f'exit code {result.returncode}'}")

    raise RuntimeError(f"下载失败: {url} ({'; '.join(errors)})")


def _parse_repo_url(repo_url: str) -> tuple[str, str] | None:
    """
    从 HTTPS/SSH 仓库地址中提取 owner/repo。

    支持：
    - https://host/owner/repo(.git)
    - ssh://git@host/owner/repo(.git)
    - git@host:owner/repo(.git)
    """
    url = repo_url.strip()
    if not url:
        return None

    patterns = [
        r"^git@[^:]+:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
        r"^ssh://git@[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
        r"^https?://[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            return match.group("owner"), match.group("repo")
    return None


def _print_remote_setup_hint(repo_dir: Path, repo_url: str, owner: str, repo: str, branch: str) -> None:
    remote = repo_url.strip() or f"git@github.com:{owner}/{repo}.git"
    console.print("\n[yellow]请先确认 GitHub 上已创建该仓库，然后执行：[/yellow]")
    console.print(f"  cd {repo_dir.resolve()}")
    console.print(f"  git remote add origin {remote}")
    console.print(f"  git branch -M {branch}")
    console.print(f"  git push -u origin {branch}")


def _setup_remote_and_push(repo_dir: Path, repo_url: str, branch: str) -> tuple[bool, str]:
    """配置 origin 并推送当前分支。"""
    if not repo_url.strip():
        return False, "未配置 GITHUB_REPO_URL"

    try:
        origin = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "未找到 git 命令"

    if origin.returncode == 0:
        current_origin = origin.stdout.strip()
        if current_origin != repo_url:
            return False, f"origin 已存在且与配置不一致: {current_origin}"
    else:
        add_origin = subprocess.run(
            ["git", "remote", "add", "origin", repo_url],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if add_origin.returncode != 0:
            err = (add_origin.stderr or add_origin.stdout).strip()
            return False, f"添加 origin 失败: {err}"

    set_branch = subprocess.run(
        ["git", "branch", "-M", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if set_branch.returncode != 0:
        err = (set_branch.stderr or set_branch.stdout).strip()
        return False, f"切换分支失败: {err}"

    verify_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if verify_head.returncode != 0:
        return False, "当前仓库还没有 commit，无法 push"

    push = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        err = (push.stderr or push.stdout).strip()
        return False, f"推送失败: {err}"

    return True, ""


def _bootstrap_repo_from_munin_source(repo_dir: Path) -> dict[str, str]:
    workflow_content = _download_text_via_curl_or_wget(PUBLISH_WORKFLOW_SOURCE_URL)
    script_content = _download_text_via_curl_or_wget(ISSUE_TO_MD_SOURCE_URL)

    file_map = {
        ".github/workflows/publish.yml": workflow_content,
        "scripts/issue_to_md.py": script_content,
    }

    results: dict[str, str] = {}
    for rel_path, content in file_map.items():
        target = repo_dir / rel_path
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        results[rel_path] = "updated" if existed else "created"

    return results


def _bootstrap_frontend(repo_dir: Path, force: bool = False) -> dict[str, str]:
    """从 munin package 复制前端模板到仓库
    
    Args:
        repo_dir: 目标仓库目录
        force: 如果目标目录已存在，是否强制覆盖
        
    Returns:
        dict[str, str]: 复制的文件列表 {相对路径: 状态}
        
    Raises:
        RuntimeError: 复制失败时抛出
        FileExistsError: 目标目录已存在且 force=False 时抛出
    """
    import shutil
    import importlib.resources as pkg_resources
    
    results: dict[str, str] = {}
    
    try:
        # 获取 munin 包中的 frontend 目录
        try:
            munin_pkg = pkg_resources.files('munin')
        except ImportError:
            raise RuntimeError("无法找到 munin package，请确保 munin 已正确安装")
        
        frontend_src = munin_pkg / 'frontend'
        
        # 验证源目录存在
        if not frontend_src.exists():
            raise RuntimeError(f"munin package 中未找到前端模板目录: {frontend_src}")
        
        frontend_dst = repo_dir / 'frontend'
        
        # 处理目标目录已存在的情况
        if frontend_dst.exists():
            if not force:
                raise FileExistsError(
                    f"目标目录已存在: {frontend_dst}"
                    f"\n使用 force=True 覆盖，或手动删除后重试"
                )
            console.print(f"[yellow]目标目录已存在，正在覆盖: {frontend_dst}[/yellow]")
            shutil.rmtree(frontend_dst)
        
        # 复制文件
        shutil.copytree(frontend_src, frontend_dst)
        
        # 统计复制的文件
        for item in frontend_dst.rglob('*'):
            if item.is_file():
                rel_path = item.relative_to(repo_dir)
                results[str(rel_path)] = 'created'
        
        if not results:
            raise RuntimeError("复制完成后未找到任何文件，请检查源目录")
        
    except FileExistsError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"复制前端模板时出错: {e}")
    
    return results


def _get_github_pages_url(config_data: dict[str, str]) -> str:
    """根据配置生成 GitHub Pages URL"""
    owner = config_data.get('GITHUB_OWNER', '')
    repo = config_data.get('GITHUB_REPO', '')
    
    if not owner or not repo:
        return ""
    
    # 用户站点: username.github.io
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    
    # 项目站点
    return f"https://{owner.lower()}.github.io/{repo}/"


def _print_github_pages_hints(config_data: dict[str, str]) -> None:
    """打印 GitHub Pages 启用提示"""
    url = _get_github_pages_url(config_data)
    owner = config_data.get('GITHUB_OWNER', '')
    repo = config_data.get('GITHUB_REPO', '')
    
    console.print("\n[bold cyan]🌐 GitHub Pages 设置指南[/bold cyan]")
    console.print("─" * 50)
    
    if url:
        console.print(f"[green]📍 部署后访问地址: {url}[/green]")
    
    console.print("\n[bold]启用 GitHub Pages 步骤:[/bold]")
    console.print("1. 访问 GitHub 仓库页面")
    console.print(f"   https://github.com/{owner}/{repo}")
    console.print("2. 点击 [bold]Settings[/bold] → [bold]Pages[/bold]")
    console.print("3. 在 'Build and deployment' 部分:")
    console.print("   - Source: 选择 [bold]'GitHub Actions'[/bold]")
    console.print("4. 保存后，首次推送将自动触发部署")
    
    console.print("\n[bold]站点配置:[/bold]")
    console.print("• 编辑 [cyan]frontend/site/config.yml[/cyan] 自定义站点信息")
    console.print("• 修改 [cyan]url[/cyan] 字段为上述访问地址")
    
    console.print("\n[yellow]⚠️ 注意: 首次部署后，GitHub Pages 可能需要几分钟才能生效[/yellow]")
    console.print("─" * 50)


def _ensure_gitignore_has_munin(repo_dir: Path) -> None:
    gitignore = repo_dir / ".gitignore"
    entry = ".munin/"

    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        if entry in lines:
            return
        content = gitignore.read_text(encoding="utf-8").rstrip("\n") + f"\n{entry}\n"
    else:
        content = f"{entry}\n"

    gitignore.write_text(content, encoding="utf-8")


def _load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values = dotenv_values(env_path)
    return {k: v for k, v in values.items() if v is not None}


def _prompt_repo_config(existing: dict[str, str], default_repo_name: str) -> dict[str, str]:
    tg_token = Prompt.ask("🤖 Telegram Bot Token", default=existing.get("TELEGRAM_BOT_TOKEN", ""))
    allowed_users = Prompt.ask("👤 允许的用户 ID (逗号分隔，可选)", default=existing.get("ALLOWED_USER_IDS", ""))
    gh_token = Prompt.ask("🔑 GitHub Personal Access Token (Repo 权限)", default=existing.get("GITHUB_TOKEN", ""))
    gh_repo_url_default = existing.get("GITHUB_REPO_URL", "").strip()
    if not gh_repo_url_default:
        legacy_owner = existing.get("GITHUB_OWNER", "").strip()
        legacy_repo = existing.get("GITHUB_REPO", default_repo_name).strip()
        if legacy_owner and legacy_repo:
            gh_repo_url_default = f"git@github.com:{legacy_owner}/{legacy_repo}.git"

    while True:
        gh_repo_url = Prompt.ask(
            "🌐 GitHub 仓库地址 (HTTPS/SSH，必填)",
            default=gh_repo_url_default,
        ).strip()
        if not gh_repo_url:
            console.print("[red]❌ GitHub 仓库地址为必填项[/red]")
            continue

        parsed = _parse_repo_url(gh_repo_url)
        if not parsed:
            console.print("[red]❌ 仓库地址无法解析，请使用标准 HTTPS/SSH 格式[/red]")
            continue

        gh_owner, gh_repo = parsed
        console.print(f"[green]已从仓库地址解析: {gh_owner}/{gh_repo}[/green]")
        break

    console.print("\n[bold]以下是可选的高级配置 (按回车使用默认值)[/bold]")
    branch = Prompt.ask("🌿 分支名", default=existing.get("GITHUB_BRANCH", "main"))
    article_dir = Prompt.ask("📂 文章存放目录", default=existing.get("ARTICLE_DIR", "content/posts"))
    image_dir = Prompt.ask("🖼️ 图片存放目录", default=existing.get("IMAGE_DIR", "content/images"))
    tz = Prompt.ask("🕒 时区", default=existing.get("JOURNAL_TZ", "Asia/Shanghai"))
    journal_label = Prompt.ask("🏷️ 日志标签", default=existing.get("JOURNAL_LABEL", "journal"))
    published_label = Prompt.ask("✅ 发布后标签", default=existing.get("PUBLISHED_LABEL", "published"))

    return {
        "TELEGRAM_BOT_TOKEN": tg_token,
        "ALLOWED_USER_IDS": allowed_users,
        "GITHUB_TOKEN": gh_token,
        "GITHUB_OWNER": gh_owner,
        "GITHUB_REPO": gh_repo,
        "GITHUB_REPO_URL": gh_repo_url,
        "GITHUB_BRANCH": branch,
        "ARTICLE_DIR": article_dir,
        "IMAGE_DIR": image_dir,
        "JOURNAL_LABEL": journal_label,
        "PUBLISHED_LABEL": published_label,
        "JOURNAL_TZ": tz,
    }


def _write_repo_env(env_path: Path, data: dict[str, str]) -> None:
    content = "\n".join(
        [
            "# Munin Repository Configuration",
            f"TELEGRAM_BOT_TOKEN={data['TELEGRAM_BOT_TOKEN']}",
            f"ALLOWED_USER_IDS={data['ALLOWED_USER_IDS']}",
            f"GITHUB_TOKEN={data['GITHUB_TOKEN']}",
            f"GITHUB_OWNER={data['GITHUB_OWNER']}",
            f"GITHUB_REPO={data['GITHUB_REPO']}",
            f"GITHUB_REPO_URL={data['GITHUB_REPO_URL']}",
            f"GITHUB_BRANCH={data['GITHUB_BRANCH']}",
            f"ARTICLE_DIR={data['ARTICLE_DIR']}",
            f"IMAGE_DIR={data['IMAGE_DIR']}",
            f"JOURNAL_LABEL={data['JOURNAL_LABEL']}",
            f"PUBLISHED_LABEL={data['PUBLISHED_LABEL']}",
            f"JOURNAL_TZ={data['JOURNAL_TZ']}",
            "",
        ]
    )
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(content, encoding="utf-8")


def _configure_repo(repo_dir: Path, force: bool) -> dict[str, str]:
    paths = _repo_paths(repo_dir)
    paths["munin_dir"].mkdir(parents=True, exist_ok=True)

    existing = _load_env_file(paths["env"])
    if paths["env"].exists() and not force:
        console.print(f"[yellow]配置文件已存在: {paths['env']}[/yellow]")
        if not Confirm.ask("是否覆盖现有配置?"):
            raise typer.Exit()

    console.print(Panel.fit(f"配置仓库: {paths['root']}", style="bold green"))
    config_data = _prompt_repo_config(existing, default_repo_name=paths["root"].name)

    _write_repo_env(paths["env"], config_data)
    _ensure_gitignore_has_munin(paths["root"])

    # 预创建内容目录，方便首次提交
    (paths["root"] / config_data["ARTICLE_DIR"]).mkdir(parents=True, exist_ok=True)
    (paths["root"] / config_data["IMAGE_DIR"]).mkdir(parents=True, exist_ok=True)

    console.print("[bold]🔧 正在写入 workflow 和脚本...[/bold]")
    try:
        results = _bootstrap_repo_from_munin_source(paths["root"])
        for file_path, status in results.items():
            if status == "created":
                console.print(f"[green]  + 已创建 {file_path}[/green]")
            else:
                console.print(f"[cyan]  ~ 已更新 {file_path}[/cyan]")
    except Exception as e:
        console.print(f"[red]⚠️ 自动初始化仓库文件失败: {e}[/red]")
        console.print("你仍可手动复制以下文件到日志仓库：")
        console.print(f"  - .github/workflows/publish.yml ({PUBLISH_WORKFLOW_SOURCE_URL})")
        console.print(f"  - scripts/issue_to_md.py ({ISSUE_TO_MD_SOURCE_URL})")

    console.print(f"[bold green]✅ 配置已保存: {paths['env']}[/bold green]")
    return config_data


def _git_init_and_commit(repo_dir: Path, repo_name: str) -> None:
    try:
        if not (repo_dir / ".git").exists():
            init_result = subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True)
            if init_result.returncode != 0:
                console.print(f"[yellow]⚠️ git init 失败: {init_result.stderr.strip()}[/yellow]")
                return

        subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True, text=True)

        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if staged.returncode == 0:
            console.print("[yellow]没有可提交的变更，跳过初始化 commit[/yellow]")
            return

        commit_msg = f"初始化完成 {repo_name}"
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            err = (commit_result.stderr or commit_result.stdout).strip()
            console.print(f"[yellow]⚠️ 初始化 commit 失败: {err}[/yellow]")
            return

        console.print(f"[bold green]✅ 已完成初始化提交: {commit_msg}[/bold green]")
    except FileNotFoundError:
        console.print("[yellow]⚠️ 未找到 git 命令，跳过初始化 commit[/yellow]")


def _read_token_from_env(env_path: Path) -> str:
    values = _load_env_file(env_path)
    token = (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(f"配置文件缺少 TELEGRAM_BOT_TOKEN: {env_path}")
    return token


def _read_repo_url_from_env(env_path: Path) -> str:
    values = _load_env_file(env_path)
    repo_url = (values.get("GITHUB_REPO_URL") or "").strip()
    if not repo_url:
        raise RuntimeError(f"配置文件缺少 GITHUB_REPO_URL: {env_path}")
    if not _parse_repo_url(repo_url):
        raise RuntimeError(f"GITHUB_REPO_URL 格式无法解析: {repo_url}")
    return repo_url


@app.command()
def new(
    repo: str = typer.Argument(..., help="新日志仓库目录名（可为相对路径）"),
    force: bool = typer.Option(False, "--force", "-f", help="强制覆盖已有配置"),
    no_frontend: bool = typer.Option(False, "--no-frontend", help="跳过前端模板初始化"),
):
    """创建并初始化一个新的日志仓库目录"""
    target = Path(repo).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if target.exists():
        if any(target.iterdir()):
            console.print(f"[yellow]目录已存在且非空: {target}[/yellow]")
            if not Confirm.ask("是否继续在该目录执行配置?"):
                raise typer.Exit()
    else:
        target.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]已创建目录: {target}[/green]")

    # 1. 配置仓库
    config_data = _configure_repo(target, force=force)
    
    # 2. Git 初始化
    git_initialized = False
    try:
        if not (target / ".git").exists():
            init_result = subprocess.run(["git", "init"], cwd=target, capture_output=True, text=True)
            if init_result.returncode == 0:
                git_initialized = True
                console.print("[green]✅ Git 仓库已初始化[/green]")
            else:
                console.print(f"[yellow]⚠️ git init 失败: {init_result.stderr.strip()}[/yellow]")
        else:
            git_initialized = True
    except FileNotFoundError:
        console.print("[yellow]⚠️ 未找到 git 命令[/yellow]")

    # 3. 可选：添加前端展示页面（在首次 commit 之前）
    frontend_added = False
    if not no_frontend and Confirm.ask("🌐 是否添加 GitHub Pages 前端展示页面？", default=True):
        console.print("[bold]🔧 正在复制前端模板...[/bold]")
        try:
            results = _bootstrap_frontend(target, force=force)
            displayed = 0
            for file_path in results:
                if displayed < 5:
                    console.print(f"[green]  + {file_path}[/green]")
                    displayed += 1
                elif displayed == 5:
                    console.print(f"[green]  ... 共 {len(results)} 个文件[/green]")
                    displayed += 1
            frontend_added = True
            console.print("[green]✅ 前端模板已添加[/green]")
        except FileExistsError as e:
            console.print(f"[yellow]⚠️ {e}[/yellow]")
            console.print("[yellow]使用 --force 选项覆盖，或手动删除后重试[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠️ 添加前端模板失败: {e}[/yellow]")
            console.print("[yellow]你可以稍后手动添加前端模板[/yellow]")

    # 4. 统一提交（包含所有初始文件）
    if git_initialized:
        try:
            subprocess.run(["git", "add", "-A"], cwd=target, capture_output=True, text=True)
            
            # 检查是否有文件待提交
            staged = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=target,
                capture_output=True,
                text=True,
            )
            if staged.returncode == 0:
                console.print("[yellow]没有可提交的变更[/yellow]")
            else:
                # 构建提交信息
                commit_parts = ["初始化仓库"]
                if frontend_added:
                    commit_parts.append("，添加前端模板")
                commit_msg = "".join(commit_parts)
                
                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=target,
                    capture_output=True,
                    text=True,
                )
                if commit_result.returncode == 0:
                    console.print(f"[bold green]✅ 已完成首次提交: {commit_msg}[/bold green]")
                else:
                    err = (commit_result.stderr or commit_result.stdout).strip()
                    console.print(f"[yellow]⚠️ 提交失败: {err}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Git 提交出错: {e}[/yellow]")

    # 5. 推送
    repo_url = config_data.get("GITHUB_REPO_URL", "").strip()
    branch = config_data.get("GITHUB_BRANCH", "main").strip()
    ok, message = _setup_remote_and_push(target, repo_url, branch)
    if ok:
        console.print("[bold green]✅ 已自动配置远端并完成首次 push[/bold green]")
    else:
        console.print(f"[yellow]⚠️ 自动推送未完成: {message}[/yellow]")
        console.print("[yellow]常见原因：GitHub 远端仓库尚未创建，或本机 SSH/Token 权限未准备好。[/yellow]")
        _print_remote_setup_hint(target, repo_url, config_data["GITHUB_OWNER"], config_data["GITHUB_REPO"], branch)

    # 打印 GitHub Pages 提示
    if frontend_added:
        _print_github_pages_hints(config_data)

    console.print("\n[bold green]🚀 新仓库初始化完成[/bold green]")
    console.print(f"下一步: [bold]cd {target}[/bold]")
    console.print("然后运行: [bold]munin start[/bold]")


@app.command()
def config(force: bool = typer.Option(False, "--force", "-f", help="强制覆盖现有配置")):
    """在当前仓库生成或更新配置（.munin/.env）"""
    _configure_repo(Path.cwd(), force=force)


@app.command()
def start(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="在后台运行 (Daemon 模式)"),
    restart: bool = typer.Option(False, "--restart", "-r", help="如果已运行，先停止再启动"),
):
    """启动当前仓库对应的 Bot"""
    paths = _repo_paths(Path.cwd())
    paths["munin_dir"].mkdir(parents=True, exist_ok=True)

    if not paths["env"].exists():
        console.print("[red]❌ 未找到仓库配置文件[/red]")
        console.print("请先运行: [bold]munin config[/bold]")
        raise typer.Exit(1)

    pid = _check_running(paths["pid"])
    if pid:
        if restart:
            stop()
            time.sleep(1)
        else:
            console.print(f"[yellow]Bot 已在运行中 (PID: {pid})[/yellow]")
            console.print("使用 [bold]munin stop[/bold] 停止，或 [bold]--restart[/bold] 重启")
            raise typer.Exit()

    try:
        token = _read_token_from_env(paths["env"])
        _read_repo_url_from_env(paths["env"])
    except RuntimeError as e:
        console.print(f"[red]❌ {e}[/red]")
        console.print("请先运行: [bold]munin config[/bold]")
        raise typer.Exit(1)

    if daemon:
        console.print("🚀 正在后台启动 Bot...")

        token_hash = ""
        log_f = open(paths["log"], "a", encoding="utf-8")
        try:
            token_hash = _acquire_token_lock(token, paths["root"], os.getpid(), state="starting")

            child_env = os.environ.copy()
            child_env["MUNIN_ENV_PATH"] = str(paths["env"])

            proc = subprocess.Popen(
                [sys.executable, "-m", "bot.main"],
                cwd=paths["root"],
                env=child_env,
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )

            paths["pid"].write_text(str(proc.pid), encoding="utf-8")
            _write_token_lock(token_hash, paths["root"], proc.pid, state="running")
            _write_proc_meta(proc.pid, paths["root"], token_hash, paths["log"])

            console.print(f"[bold green]✅ Bot 已在后台启动 (PID: {proc.pid})[/bold green]")
            console.print(f"📄 日志文件: {paths['log']}")
            console.print("使用 [bold]munin logs[/bold] 查看实时日志")
        except Exception as e:
            if token_hash:
                _release_token_lock(token_hash, expected_repo=paths["root"])
            console.print(f"[red]启动失败: {e}[/red]")
            raise typer.Exit(1)
        finally:
            log_f.close()

        return

    # 前台运行
    token_hash = ""
    try:
        token_hash = _acquire_token_lock(token, paths["root"], os.getpid(), state="running")
        _write_proc_meta(os.getpid(), paths["root"], token_hash, paths["log"])

        console.print("[bold green]🚀 正在前台启动 Bot (按 Ctrl+C 停止)...[/bold green]")
        from bot.main import main

        main(env_path=paths["env"])
    except RuntimeError as e:
        console.print(f"[red]❌ 启动被拒绝: {e}[/red]")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot 已停止[/yellow]")
    finally:
        if token_hash:
            _release_token_lock(token_hash, expected_repo=paths["root"])
        _remove_proc_meta(os.getpid())


@app.command()
def stop():
    """停止当前仓库后台运行的 Bot"""
    paths = _repo_paths(Path.cwd())
    pid = _check_running(paths["pid"])

    if not pid:
        console.print("[yellow]当前仓库没有运行中的 Bot[/yellow]")
        return

    token_hash = None
    if paths["env"].exists():
        token = (_load_env_file(paths["env"]).get("TELEGRAM_BOT_TOKEN") or "").strip()
        if token:
            token_hash = _hash_token(token)

    try:
        console.print(f"正在停止 PID {pid}...")
        os.kill(pid, signal.SIGTERM)

        for _ in range(50):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)

        if _pid_alive(pid):
            console.print("[red]停止超时，尝试强制停止...[/red]")
            os.kill(pid, signal.SIGKILL)

        console.print(f"[green]✅ Bot (PID {pid}) 已停止[/green]")
    except ProcessLookupError:
        console.print("[yellow]进程已不存在[/yellow]")
    except Exception as e:
        console.print(f"[red]停止出错: {e}[/red]")
    finally:
        paths["pid"].unlink(missing_ok=True)
        _remove_proc_meta(pid)
        if token_hash:
            _release_token_lock(token_hash, expected_repo=paths["root"], expected_pid=pid)


@app.command()
def status():
    """查看当前仓库运行状态"""
    paths = _repo_paths(Path.cwd())
    pid = _check_running(paths["pid"])

    config_state = "✅ 存在" if paths["env"].exists() else "❌ 不存在"
    lock_state = "-"

    if paths["env"].exists():
        token = (_load_env_file(paths["env"]).get("TELEGRAM_BOT_TOKEN") or "").strip()
        if token:
            token_hash = _hash_token(token)
            _cleanup_stale_token_lock(token_hash)
            lock_state = "🔒 占用" if _token_lock_path(token_hash).exists() else "🔓 空闲"

    table = f"""
    [bold]状态检查[/bold]

    仓库路径: {paths['root']}
    配置路径: {paths['env']} ({config_state})
    日志路径: {paths['log']}
    运行状态: {"🟢 运行中" if pid else "⚪️ 未运行"}
    PID: {pid if pid else "-"}
    Token 锁: {lock_state}
    """
    console.print(Panel(table.strip(), title="Munin Status", expand=False))


@app.command()
def logs(lines: int = typer.Option(20, "--lines", "-n", help="显示最后 N 行")):
    """查看当前仓库日志 (tail -f)"""
    paths = _repo_paths(Path.cwd())
    if not paths["log"].exists():
        console.print("[yellow]当前仓库日志文件不存在[/yellow]")
        return

    console.print(f"[bold]显示最后 {lines} 行日志 (Ctrl+C 退出):[/bold]")
    try:
        subprocess.run(["tail", "-f", "-n", str(lines), str(paths["log"])])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    app()
