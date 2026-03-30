"""Tests for the file walker and profile system."""

import os
from pathlib import Path

import pytest

from codebase_analyzer.walker import (
    Profile,
    SkippedFile,
    detect_profiles,
    is_binary,
    load_bundled_profiles,
    load_profile,
    merge_profiles,
    walk_repo,
)


@pytest.fixture
def sample_repo(tmp_path):
    """Create a sample repo structure for testing."""
    # Python files
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    (tmp_path / "setup.py").write_text("from setuptools import setup")
    (tmp_path / "requirements.txt").write_text("click\nrich\n")

    # Subdirectory
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "core.py").write_text("class Core: pass")
    (tmp_path / "lib" / "__init__.py").write_text("")

    # Config
    (tmp_path / "config.yaml").write_text("key: value")

    # JS file (should not match python profile)
    (tmp_path / "script.js").write_text("console.log('hi')")

    # Binary file
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # .git directory
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")

    # __pycache__
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00" * 50)

    # .gitignore
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")

    # Files that should be gitignored
    (tmp_path / "debug.log").write_text("log entry")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "output.py").write_text("compiled = True")

    return tmp_path


class TestProfileLoading:
    def test_load_bundled_profiles(self):
        profiles = load_bundled_profiles()
        assert "python" in profiles
        assert "javascript" in profiles
        assert "go" in profiles

    def test_bundled_python_profile(self):
        profiles = load_bundled_profiles()
        py = profiles["python"]
        assert ".py" in py.extensions
        assert ".pyx" in py.extensions
        assert "__pycache__" in py.exclude_dirs
        assert "setup.py" in py.markers

    def test_load_custom_profile(self, tmp_path):
        profile_file = tmp_path / "custom.yaml"
        profile_file.write_text(
            "name: custom\n"
            "extensions: [.xyz, .abc]\n"
            "include_patterns: []\n"
            "exclude_dirs: []\n"
            "markers: [custom.lock]\n"
        )
        profile = load_profile(profile_file)
        assert profile.name == "custom"
        assert ".xyz" in profile.extensions

    def test_profile_missing_optional_fields(self, tmp_path):
        profile_file = tmp_path / "minimal.yaml"
        profile_file.write_text("name: minimal\n")
        profile = load_profile(profile_file)
        assert profile.name == "minimal"
        assert profile.extensions == []
        assert profile.markers == []


class TestProfileDetection:
    def test_detect_python(self, sample_repo):
        profiles = load_bundled_profiles()
        detected = detect_profiles(sample_repo, profiles)
        assert "python" in detected

    def test_detect_javascript(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        profiles = load_bundled_profiles()
        detected = detect_profiles(tmp_path, profiles)
        assert "javascript" in detected

    def test_detect_multiple(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "package.json").write_text("{}")
        profiles = load_bundled_profiles()
        detected = detect_profiles(tmp_path, profiles)
        assert "python" in detected
        assert "javascript" in detected

    def test_detect_none(self, tmp_path):
        (tmp_path / "readme.txt").write_text("just a readme")
        profiles = load_bundled_profiles()
        detected = detect_profiles(tmp_path, profiles)
        assert detected == []

    def test_auto_includes_config_devops_web(self, sample_repo):
        profiles = load_bundled_profiles()
        detected = detect_profiles(sample_repo, profiles)
        assert "config" in detected
        assert "devops" in detected
        assert "web" in detected


class TestMergeProfiles:
    def test_merge_extensions(self):
        p1 = Profile(name="a", extensions=[".py", ".pyx"])
        p2 = Profile(name="b", extensions=[".js", ".py"])
        exts, _, _ = merge_profiles([p1, p2])
        assert exts == {".py", ".pyx", ".js"}

    def test_merge_exclude_dirs(self):
        p1 = Profile(name="a", exclude_dirs=["__pycache__", "venv"])
        p2 = Profile(name="b", exclude_dirs=["node_modules", "venv"])
        _, dirs, _ = merge_profiles([p1, p2])
        assert dirs == {"__pycache__", "venv", "node_modules"}

    def test_merge_include_patterns(self):
        p1 = Profile(name="a", include_patterns=["setup.py"])
        p2 = Profile(name="b", include_patterns=["package.json"])
        _, _, patterns = merge_profiles([p1, p2])
        assert "setup.py" in patterns
        assert "package.json" in patterns


class TestBinaryDetection:
    def test_binary_by_extension(self, tmp_path):
        png = tmp_path / "test.png"
        png.write_text("not actually a png")
        assert is_binary(png)

    def test_binary_by_null_bytes(self, tmp_path):
        binfile = tmp_path / "data.custom"
        binfile.write_bytes(b"some text\x00more text")
        assert is_binary(binfile)

    def test_text_file(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("just plain text")
        assert not is_binary(txt)

    def test_python_file_not_binary(self, tmp_path):
        py = tmp_path / "script.py"
        py.write_text("print('hello')")
        assert not is_binary(py)


class TestWalkRepo:
    def test_walks_python_files(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert "main.py" in result.files
        assert "utils.py" in result.files
        assert "lib/core.py" in result.files

    def test_includes_profile_include_patterns(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert "setup.py" in result.files
        assert "requirements.txt" in result.files

    def test_excludes_git_directory(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        git_files = [f for f in result.files if ".git/" in f]
        assert git_files == []

    def test_excludes_pycache(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        cache_files = [f for f in result.files if "__pycache__" in f]
        assert cache_files == []

    def test_excludes_gitignored_files(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert "debug.log" not in result.files
        assert "build/output.py" not in result.files

    def test_skips_binary_files(self, sample_repo):
        result = walk_repo(sample_repo, all_text_files=True)
        assert "image.png" not in result.files
        skipped_paths = [s.path for s in result.skipped]
        assert "image.png" in skipped_paths

    def test_skips_empty_files(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert "lib/__init__.py" not in result.files
        skipped_paths = [s.path for s in result.skipped]
        assert "lib/__init__.py" in skipped_paths

    def test_all_text_files_mode(self, sample_repo):
        result = walk_repo(sample_repo, all_text_files=True)
        assert "main.py" in result.files
        assert "script.js" in result.files
        assert "config.yaml" in result.files

    def test_js_excluded_by_python_profile(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert "script.js" not in result.files

    def test_auto_detect_profiles(self, sample_repo):
        result = walk_repo(sample_repo)
        assert "python" in result.profiles_used
        assert "main.py" in result.files

    def test_unknown_profile_raises(self, sample_repo):
        with pytest.raises(ValueError, match="Unknown profiles"):
            walk_repo(sample_repo, profiles="nonexistent")

    def test_custom_profile_file(self, sample_repo, tmp_path):
        profile_file = tmp_path / "custom.yaml"
        profile_file.write_text(
            "name: custom\n"
            "extensions: [.js]\n"
            "include_patterns: []\n"
            "exclude_dirs: []\n"
            "markers: []\n"
        )
        result = walk_repo(sample_repo, profile_file=profile_file, profiles="custom")
        assert "script.js" in result.files
        assert "main.py" not in result.files

    def test_large_file_still_included_but_flagged(self, sample_repo):
        large = sample_repo / "big.py"
        large.write_text("x = 1\n" * 20_000)
        result = walk_repo(sample_repo, profiles="python", max_file_size=1000)
        assert "big.py" in result.files
        large_skipped = [s for s in result.skipped if s.path == "big.py"]
        assert len(large_skipped) == 1
        assert "will be chunked" in large_skipped[0].reason

    def test_files_are_sorted(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python")
        assert result.files == sorted(result.files)

    def test_fallback_to_all_text_when_no_profiles_detected(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.csv").write_text("a,b,c")
        result = walk_repo(tmp_path)
        assert len(result.files) == 2
        assert any("fallback" in p for p in result.profiles_used)

    def test_multiple_profiles(self, sample_repo):
        result = walk_repo(sample_repo, profiles="python,config")
        assert "main.py" in result.files
        assert "config.yaml" in result.files
