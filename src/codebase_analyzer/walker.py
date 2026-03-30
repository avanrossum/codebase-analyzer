"""File discovery and profile system for traversing codebases."""

import fnmatch
import importlib.resources
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pathspec
import yaml


# Known binary extensions — files with these are always skipped
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac", ".ogg",
    ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".sqlite", ".db", ".sqlite3",
    ".bin", ".dat", ".pkl", ".pickle", ".npy", ".npz",
    ".DS_Store",
})

SNIFF_SIZE = 8192  # bytes to read for null-byte detection


@dataclass
class Profile:
    """A language profile defining which files to include/exclude."""

    name: str
    extensions: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    exclude_dirs: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)


@dataclass
class SkippedFile:
    """Record of a file that was skipped during walking."""

    path: str
    reason: str


@dataclass
class WalkResult:
    """Result of walking a repository."""

    files: list[str]
    skipped: list[SkippedFile]
    profiles_used: list[str]


def load_profile(path: Path) -> Profile:
    """Load a single profile from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return Profile(
        name=data["name"],
        extensions=data.get("extensions", []),
        include_patterns=data.get("include_patterns", []),
        exclude_dirs=data.get("exclude_dirs", []),
        markers=data.get("markers", []),
    )


def load_bundled_profiles() -> dict[str, Profile]:
    """Load all bundled profiles from the package."""
    profiles = {}
    profiles_dir = importlib.resources.files("codebase_analyzer") / "profiles"
    for item in profiles_dir.iterdir():
        if item.name.endswith(".yaml"):
            path = Path(str(item))
            profile = load_profile(path)
            profiles[profile.name] = profile
    return profiles


def detect_profiles(repo_path: Path, available: dict[str, Profile]) -> list[str]:
    """Auto-detect which profiles apply by checking for marker files in the repo root."""
    detected = []
    root_contents = set()
    for entry in os.scandir(repo_path):
        root_contents.add(entry.name)

    for name, profile in available.items():
        for marker in profile.markers:
            if marker in root_contents:
                detected.append(name)
                break

    # Always include config and devops if any language profile is detected
    if detected:
        for always_include in ("config", "devops", "web"):
            if always_include in available and always_include not in detected:
                detected.append(always_include)

    return sorted(detected)


def merge_profiles(profiles: list[Profile]) -> tuple[set[str], set[str], list[str]]:
    """Merge multiple profiles into combined sets.

    Returns (extensions, exclude_dirs, include_patterns).
    """
    extensions: set[str] = set()
    exclude_dirs: set[str] = set()
    include_patterns: list[str] = []

    for p in profiles:
        extensions.update(p.extensions)
        exclude_dirs.update(p.exclude_dirs)
        include_patterns.extend(p.include_patterns)

    return extensions, exclude_dirs, include_patterns


def is_binary(file_path: Path) -> bool:
    """Check if a file is binary by extension and null-byte sniffing."""
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(SNIFF_SIZE)
            return b"\x00" in chunk
    except (OSError, PermissionError):
        return True


def load_gitignore(repo_path: Path) -> Optional[pathspec.PathSpec]:
    """Load .gitignore patterns from the repo root."""
    gitignore_path = repo_path / ".gitignore"
    if not gitignore_path.exists():
        return None
    with open(gitignore_path) as f:
        return pathspec.PathSpec.from_lines("gitignore", f)


def walk_repo(
    repo_path: Path,
    profiles: Optional[list[str]] = None,
    profile_file: Optional[Path] = None,
    all_text_files: bool = False,
    max_file_size: int = 100_000,
) -> WalkResult:
    """Walk a repository and return files eligible for analysis.

    Args:
        repo_path: Root directory of the repository.
        profiles: Comma-separated profile names, or None for auto-detect.
        profile_file: Path to a custom profile YAML file.
        all_text_files: If True, include all non-binary text files regardless of profile.
        max_file_size: Files larger than this (bytes) are included but flagged.
            The analyzer handles chunking — walker just reports size.
    """
    repo_path = Path(repo_path).resolve()
    skipped: list[SkippedFile] = []

    # Load profiles
    available = load_bundled_profiles()

    if profile_file:
        custom = load_profile(Path(profile_file))
        available[custom.name] = custom

    if profiles:
        profile_names = [p.strip() for p in profiles.split(",")]
        missing = [p for p in profile_names if p not in available]
        if missing:
            raise ValueError(f"Unknown profiles: {', '.join(missing)}")
        active = [available[p] for p in profile_names]
    elif all_text_files:
        active = []
        profile_names = ["all-text-files"]
    else:
        detected = detect_profiles(repo_path, available)
        if not detected:
            # Fall back to all text files if nothing detected
            active = []
            profile_names = ["all-text-files (fallback)"]
            all_text_files = True
        else:
            active = [available[name] for name in detected]
            profile_names = detected

    # Merge profile rules
    if active:
        extensions, exclude_dirs, include_patterns = merge_profiles(active)
    else:
        extensions, exclude_dirs, include_patterns = set(), set(), []

    # Load .gitignore
    gitignore = load_gitignore(repo_path)

    # Walk
    files: list[str] = []

    for dirpath, dirnames, filenames in os.walk(repo_path):
        rel_dir = os.path.relpath(dirpath, repo_path)

        # Always skip .git
        if ".git" in dirnames:
            dirnames.remove(".git")

        # Filter excluded directories
        dirnames[:] = [
            d for d in dirnames
            if not _is_excluded_dir(d, exclude_dirs)
            and not _gitignore_match(gitignore, os.path.join(rel_dir, d) + "/")
        ]

        for filename in filenames:
            abs_path = Path(dirpath) / filename
            rel_path = os.path.relpath(abs_path, repo_path)

            # Normalize path separators
            rel_path = rel_path.replace(os.sep, "/")

            # Check .gitignore
            if _gitignore_match(gitignore, rel_path):
                continue

            # Check binary
            if is_binary(abs_path):
                skipped.append(SkippedFile(rel_path, "binary file"))
                continue

            # Check file size
            try:
                size = abs_path.stat().st_size
            except OSError:
                skipped.append(SkippedFile(rel_path, "unable to stat"))
                continue

            if size == 0:
                skipped.append(SkippedFile(rel_path, "empty file"))
                continue

            # Profile matching (skip if not all_text_files mode)
            if not all_text_files:
                if not _matches_profile(filename, rel_path, extensions, include_patterns):
                    continue

            # File passes all filters
            if size > max_file_size:
                skipped.append(SkippedFile(rel_path, f"large file ({size:,} bytes) — will be chunked"))

            files.append(rel_path)

    files.sort()
    return WalkResult(files=files, skipped=skipped, profiles_used=profile_names)


def _is_excluded_dir(dirname: str, exclude_dirs: set[str]) -> bool:
    """Check if a directory name matches any exclusion pattern."""
    for pattern in exclude_dirs:
        if fnmatch.fnmatch(dirname, pattern):
            return True
    return False


def _gitignore_match(gitignore: Optional[pathspec.PathSpec], rel_path: str) -> bool:
    """Check if a path matches .gitignore patterns."""
    if gitignore is None:
        return False
    # Normalize the path for matching
    if rel_path.startswith("./"):
        rel_path = rel_path[2:]
    return gitignore.match_file(rel_path)


def _matches_profile(
    filename: str,
    rel_path: str,
    extensions: set[str],
    include_patterns: list[str],
) -> bool:
    """Check if a file matches any active profile's extensions or include patterns."""
    # Check extension
    _, ext = os.path.splitext(filename)
    if ext.lower() in extensions:
        return True

    # Check include patterns (matched against full relative path or filename)
    for pattern in include_patterns:
        if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True

    return False
