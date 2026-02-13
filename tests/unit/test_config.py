"""
Config 模块单元测试

测试配置加载、验证和默认值。
"""

from __future__ import annotations

import os
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from bot.config import Config, _require


@pytest.mark.unit
class TestConfigLoading:
    """测试配置加载功能。"""

    def test_config_from_env(self, test_config: Config) -> None:
        """测试从环境变量加载配置。"""
        assert test_config.telegram_token == "test_telegram_token"
        assert test_config.github_token == "test_github_token"
        assert test_config.github_owner == "test_owner"
        assert test_config.github_repo == "test_repo"
        assert test_config.branch == "main"

    def test_config_allowed_user_ids(self, test_config: Config) -> None:
        """测试白名单用户 ID 列表解析。"""
        assert test_config.allowed_user_ids == (123456789, 987654321)

    def test_config_empty_whitelist(self, test_config_no_whitelist: Config) -> None:
        """测试空白名单（允许所有用户）。"""
        assert test_config_no_whitelist.allowed_user_ids == ()

    def test_config_timezone(self, test_config: Config) -> None:
        """测试时区设置。"""
        assert test_config.timezone == ZoneInfo("Asia/Shanghai")

    def test_config_default_values(self, test_config: Config) -> None:
        """测试默认值。"""
        assert test_config.article_dir == "content/posts"
        assert test_config.image_dir == "content/images"
        assert test_config.journal_label == "journal"
        assert test_config.published_label == "published"


@pytest.mark.unit
class TestConfigFromEnvVars:
    """测试从环境变量构建配置。"""

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "env_telegram_token",
            "GITHUB_TOKEN": "env_github_token",
            "GITHUB_OWNER": "env_owner",
            "GITHUB_REPO": "env_repo",
            "ALLOWED_USER_IDS": "111,222,333",
            "GITHUB_BRANCH": "develop",
            "ARTICLE_DIR": "posts",
            "IMAGE_DIR": "images",
            "JOURNAL_LABEL": "daily",
            "PUBLISHED_LABEL": "done",
            "JOURNAL_TZ": "America/New_York",
        },
        clear=True,
    )
    def test_load_from_env_vars(self) -> None:
        """测试从环境变量加载所有配置。"""
        config = Config.from_env(load_dotenv_file=False)

        assert config.telegram_token == "env_telegram_token"
        assert config.github_token == "env_github_token"
        assert config.github_owner == "env_owner"
        assert config.github_repo == "env_repo"
        assert config.allowed_user_ids == (111, 222, 333)
        assert config.branch == "develop"
        assert config.article_dir == "posts"
        assert config.image_dir == "images"
        assert config.journal_label == "daily"
        assert config.published_label == "done"
        assert config.timezone == ZoneInfo("America/New_York")

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "GITHUB_TOKEN": "token",
            "GITHUB_OWNER": "owner",
            "GITHUB_REPO": "repo",
            "ALLOWED_USER_IDS": "",
        },
        clear=True,
    )
    def test_empty_user_ids(self) -> None:
        """测试空用户 ID 环境变量。"""
        config = Config.from_env(load_dotenv_file=False)
        assert config.allowed_user_ids == ()

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "GITHUB_TOKEN": "token",
            "GITHUB_OWNER": "owner",
            "GITHUB_REPO": "repo",
            "ALLOWED_USER_IDS": "  111  ,  222  ",
        },
        clear=True,
    )
    def test_whitespace_in_user_ids(self) -> None:
        """测试用户 ID 中的空格处理。"""
        config = Config.from_env(load_dotenv_file=False)
        assert config.allowed_user_ids == (111, 222)


@pytest.mark.unit
class TestConfigValidation:
    """测试配置验证。"""

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_telegram_token(self, capsys) -> None:
        """测试缺少 TELEGRAM_BOT_TOKEN 时退出。"""
        with pytest.raises(SystemExit) as exc_info:
            Config.from_env(load_dotenv_file=False)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TELEGRAM_BOT_TOKEN" in captured.out

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
        },
        clear=True,
    )
    def test_missing_required_github_token(self, capsys) -> None:
        """测试缺少 GITHUB_TOKEN 时退出。"""
        with pytest.raises(SystemExit) as exc_info:
            Config.from_env(load_dotenv_file=False)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "GITHUB_TOKEN" in captured.out

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "GITHUB_TOKEN": "token",
            "GITHUB_OWNER": "owner",
            "GITHUB_REPO": "repo",
            "JOURNAL_TZ": "Invalid/Timezone",
        },
        clear=True,
    )
    def test_invalid_timezone_fallback(self, capsys) -> None:
        """测试无效时区回退到默认值。"""
        config = Config.from_env(load_dotenv_file=False)
        assert config.timezone == ZoneInfo("Asia/Shanghai")

        captured = capsys.readouterr()
        assert "无法识别时区" in captured.out


@pytest.mark.unit
class TestRequireFunction:
    """测试 _require 辅助函数。"""

    def test_require_existing_var(self) -> None:
        """测试读取存在的环境变量。"""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            assert _require("TEST_VAR") == "test_value"

    def test_require_strip_whitespace(self) -> None:
        """测试去除空白字符。"""
        with patch.dict(os.environ, {"TEST_VAR": "  value  "}):
            assert _require("TEST_VAR") == "value"

    def test_require_missing_var(self, capsys) -> None:
        """测试缺少环境变量时退出。"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                _require("MISSING_VAR")

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "MISSING_VAR" in captured.out
            assert "请检查 .env 文件" in captured.out

    def test_require_empty_var(self, capsys) -> None:
        """测试空环境变量视为缺失。"""
        with patch.dict(os.environ, {"EMPTY_VAR": ""}):
            with pytest.raises(SystemExit) as exc_info:
                _require("EMPTY_VAR")

            assert exc_info.value.code == 1


@pytest.mark.unit
class TestConfigImmutability:
    """测试配置的不可变性。"""

    def test_config_is_frozen(self, test_config: Config) -> None:
        """测试配置对象不可修改。"""
        with pytest.raises(AttributeError):
            test_config.telegram_token = "new_token"

    def test_config_hashable(self, test_config: Config) -> None:
        """测试配置对象可作为字典 key。"""
        # frozen dataclass 应该是可哈希的
        d = {test_config: "value"}
        assert d[test_config] == "value"


@pytest.mark.unit
class TestConfigEdgeCases:
    """测试边界情况。"""

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "GITHUB_TOKEN": "token",
            "GITHUB_OWNER": "owner",
            "GITHUB_REPO": "repo",
            "ALLOWED_USER_IDS": "abc,def,ghi",
        },
        clear=True,
    )
    def test_invalid_user_ids_format(self) -> None:
        """测试无效的用户 ID 格式应该报错。"""
        with pytest.raises(ValueError):
            Config.from_env(load_dotenv_file=False)

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "GITHUB_TOKEN": "token",
            "GITHUB_OWNER": "owner",
            "GITHUB_REPO": "repo",
        },
        clear=True,
    )
    def test_config_str_path(self) -> None:
        """测试字符串路径处理。"""
        config = Config.from_env()
        # article_dir 和 image_dir 应该是字符串
        assert isinstance(config.article_dir, str)
        assert isinstance(config.image_dir, str)
