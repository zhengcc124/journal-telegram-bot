#!/usr/bin/env python3
"""
手动测试 _bootstrap_frontend 函数
用于验证 munin package 中的前端文件可以正确复制
"""

import shutil

# 确保可以导入 bot.cli
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console

from bot.cli import _bootstrap_frontend, _get_github_pages_url, _print_github_pages_hints

console = Console()


def test_bootstrap_frontend_real():
    """使用真实的 munin package 测试前端复制功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "test_repo"
        target.mkdir()

        console.print("[bold]测试 1: 正常复制前端文件[/bold]")
        try:
            results = _bootstrap_frontend(target)
            console.print(f"[green]✅ 成功复制 {len(results)} 个文件[/green]")
            for i, path in enumerate(list(results.keys())[:3]):
                console.print(f"  + {path}")
            if len(results) > 3:
                console.print(f"  ... 共 {len(results)} 个文件")
        except Exception as e:
            console.print(f"[red]❌ 失败: {e}[/red]")
            return False

        console.print("\n[bold]测试 2: 目标已存在，force=False[/bold]")
        try:
            _bootstrap_frontend(target, force=False)
            console.print("[red]❌ 应该抛出 FileExistsError[/red]")
            return False
        except FileExistsError as e:
            console.print(f"[green]✅ 正确抛出 FileExistsError: {e}[/green]")
        except Exception as e:
            console.print(f"[red]❌ 抛出错误类型不对: {e}[/red]")
            return False

        console.print("\n[bold]测试 3: 目标已存在，force=True[/bold]")
        (target / "frontend" / "old_file.txt").write_text("old")
        try:
            results = _bootstrap_frontend(target, force=True)
            if not (target / "frontend" / "old_file.txt").exists():
                console.print("[green]✅ force=True 正确覆盖旧文件[/green]")
            else:
                console.print("[red]❌ 旧文件仍然存在[/red]")
                return False
        except Exception as e:
            console.print(f"[red]❌ 失败: {e}[/red]")
            return False

        console.print("\n[bold]测试 4: GitHub Pages URL 生成[/bold]")
        test_cases = [
            (
                {"GITHUB_OWNER": "JohnDoe", "GITHUB_REPO": "johndoe.github.io"},
                "https://johndoe.github.io/",
            ),
            (
                {"GITHUB_OWNER": "MyOrg", "GITHUB_REPO": "my-project"},
                "https://myorg.github.io/my-project/",
            ),
            ({}, ""),
        ]
        for config, expected in test_cases:
            result = _get_github_pages_url(config)
            if result == expected:
                console.print(f"[green]✅ {config} -> {result}[/green]")
            else:
                console.print(f"[red]❌ {config} -> {result} (期望: {expected})[/red]")
                return False

        console.print("\n[bold]测试 5: GitHub Pages 提示信息[/bold]")
        config = {"GITHUB_OWNER": "testuser", "GITHUB_REPO": "testrepo"}
        _print_github_pages_hints(config)

    return True


if __name__ == "__main__":
    console.print("=" * 60)
    console.print("[bold cyan]Munin 前端模板复制功能测试[/bold cyan]")
    console.print("=" * 60)

    success = test_bootstrap_frontend_real()

    console.print("\n" + "=" * 60)
    if success:
        console.print("[bold green]所有测试通过! ✅[/bold green]")
    else:
        console.print("[bold red]测试失败! ❌[/bold red]")
    console.print("=" * 60)
