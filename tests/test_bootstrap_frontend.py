"""Tests for _bootstrap_frontend function in bot/cli.py"""

import os
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the function to test (we'll need to import from cli module)
# Note: bot/cli.py uses typer and rich, so we need to handle imports carefully


class TestBootstrapFrontend:
    """Test suite for _bootstrap_frontend function"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing"""
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_frontend_files(self):
        """Create mock frontend files structure"""
        def _create(base_path: Path):
            # Create mock structure similar to munin/frontend/
            (base_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
            (base_path / "site" / "templates").mkdir(parents=True, exist_ok=True)
            (base_path / "site" / "assets" / "css").mkdir(parents=True, exist_ok=True)
            
            (base_path / ".github" / "workflows" / "deploy.yml").write_text("deploy workflow")
            (base_path / "site" / "build.py").write_text("build script")
            (base_path / "site" / "config.yml").write_text("config")
            (base_path / "site" / "templates" / "index.html").write_text("<html></html>")
            (base_path / "site" / "assets" / "css" / "style.css").write_text("body {}")
        
        return _create

    def test_bootstrap_frontend_success(self, temp_dir, mock_frontend_files):
        """Test successful frontend bootstrap"""
        # Create a mock munin package structure
        mock_munin_dir = temp_dir / "mock_munin"
        mock_frontend_dir = mock_munin_dir / "frontend"
        mock_frontend_dir.mkdir(parents=True)
        mock_frontend_files(mock_frontend_dir)
        
        # Create a target repo
        target_repo = temp_dir / "test_repo"
        target_repo.mkdir()
        
        # Mock importlib.resources.files - need to simulate files('munin') / 'frontend'
        # files('munin') returns the munin package dir, then / 'frontend' gives frontend subdir
        with patch('importlib.resources.files') as mock_files:
            # Return the parent dir (mock_munin_dir) so that / 'frontend' gives mock_frontend_dir
            mock_files.return_value = mock_munin_dir
            
            # Import and test
            from bot.cli import _bootstrap_frontend
            
            results = _bootstrap_frontend(target_repo)
            
            # Verify results
            assert len(results) == 5  # 5 files created
            assert (target_repo / "frontend" / "site" / "build.py").exists()
            assert (target_repo / "frontend" / "site" / "templates" / "index.html").exists()

    def test_bootstrap_frontend_target_exists_no_force(self, temp_dir, mock_frontend_files):
        """Test that FileExistsError is raised when target exists and force=False"""
        # Setup mock
        mock_munin_dir = temp_dir / "mock_munin"
        mock_frontend_dir = mock_munin_dir / "frontend"
        mock_frontend_dir.mkdir(parents=True)
        mock_frontend_files(mock_frontend_dir)
        
        target_repo = temp_dir / "test_repo"
        target_repo.mkdir()
        (target_repo / "frontend").mkdir()  # Pre-create frontend dir
        (target_repo / "frontend" / "existing.txt").write_text("existing")
        
        with patch('importlib.resources.files') as mock_files:
            mock_files.return_value = mock_munin_dir
            
            from bot.cli import _bootstrap_frontend
            
            with pytest.raises(FileExistsError) as exc_info:
                _bootstrap_frontend(target_repo, force=False)
            
            assert "目标目录已存在" in str(exc_info.value)
            # Verify existing file still exists
            assert (target_repo / "frontend" / "existing.txt").exists()

    def test_bootstrap_frontend_target_exists_with_force(self, temp_dir, mock_frontend_files):
        """Test that target is overwritten when force=True"""
        mock_munin_dir = temp_dir / "mock_munin"
        mock_frontend_dir = mock_munin_dir / "frontend"
        mock_frontend_dir.mkdir(parents=True)
        mock_frontend_files(mock_frontend_dir)
        
        target_repo = temp_dir / "test_repo"
        target_repo.mkdir()
        (target_repo / "frontend").mkdir()
        (target_repo / "frontend" / "old_file.txt").write_text("old content")
        
        with patch('importlib.resources.files') as mock_files:
            mock_files.return_value = mock_munin_dir
            
            from bot.cli import _bootstrap_frontend
            
            results = _bootstrap_frontend(target_repo, force=True)
            
            # Verify old file is gone
            assert not (target_repo / "frontend" / "old_file.txt").exists()
            # Verify new files exist
            assert (target_repo / "frontend" / "site" / "build.py").exists()

    def test_bootstrap_frontend_package_not_found(self, temp_dir):
        """Test error when munin package is not found"""
        target_repo = temp_dir / "test_repo"
        target_repo.mkdir()
        
        with patch('importlib.resources.files') as mock_files:
            mock_files.side_effect = ImportError("No package named 'munin'")
            
            from bot.cli import _bootstrap_frontend
            
            with pytest.raises(RuntimeError) as exc_info:
                _bootstrap_frontend(target_repo)
            
            assert "无法找到 munin package" in str(exc_info.value)

    def test_bootstrap_frontend_source_not_found(self, temp_dir):
        """Test error when frontend source directory doesn't exist"""
        target_repo = temp_dir / "test_repo"
        target_repo.mkdir()
        
        with patch('importlib.resources.files') as mock_files:
            mock_pkg = MagicMock()
            # Create a path that doesn't exist
            nonexistent_path = temp_dir / "nonexistent" / "frontend"
            mock_pkg.__truediv__ = lambda self, x: nonexistent_path
            mock_files.return_value = mock_pkg
            
            from bot.cli import _bootstrap_frontend
            
            with pytest.raises(RuntimeError) as exc_info:
                _bootstrap_frontend(target_repo)
            
            assert "未找到前端模板目录" in str(exc_info.value)


class TestGitHubPagesUrl:
    """Test suite for GitHub Pages URL generation"""

    def test_user_site_url(self):
        """Test URL for user site (username.github.io repo)"""
        from bot.cli import _get_github_pages_url
        
        config = {
            "GITHUB_OWNER": "JohnDoe",
            "GITHUB_REPO": "johndoe.github.io"
        }
        url = _get_github_pages_url(config)
        assert url == "https://johndoe.github.io/"

    def test_project_site_url(self):
        """Test URL for project site"""
        from bot.cli import _get_github_pages_url
        
        config = {
            "GITHUB_OWNER": "MyOrg",
            "GITHUB_REPO": "my-project"
        }
        url = _get_github_pages_url(config)
        assert url == "https://myorg.github.io/my-project/"

    def test_missing_config(self):
        """Test with missing config values"""
        from bot.cli import _get_github_pages_url
        
        assert _get_github_pages_url({}) == ""
        assert _get_github_pages_url({"GITHUB_OWNER": "test"}) == ""
        assert _get_github_pages_url({"GITHUB_REPO": "test"}) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])