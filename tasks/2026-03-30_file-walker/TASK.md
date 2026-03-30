# Task: File Walker

## Summary
Implement the file discovery and profile system that traverses a target repo, applies language profiles and exclusion rules, detects binary files, and produces the list of files to analyze.

## Spec
Per `codebase-analyzer-spec.md`:

### Profile System
- Profiles are YAML files defining: `name`, `extensions`, `include_patterns`, `exclude_dirs`, `markers`
- Profiles are composable — multiple can be active simultaneously
- Auto-detection: scan repo root for marker files (`setup.py` → python, `package.json` → javascript, etc.)
- Custom profile file support via `--profile-file`
- `--all-text-files` mode bypasses profiles, includes everything non-binary

### Universal Excludes (always applied)
- `.git/`
- Paths matching `.gitignore` patterns (via `pathspec`)
- Binary files (detected by extension AND null-byte sniffing first 8KB)
- Files larger than configurable limit (default 100KB) — logged as skipped with reason

### Profile Loading
- Bundled profiles live in `src/codebase_analyzer/profiles/`
- User profiles can be at `~/.codebase-analyzer/profiles/` (future)
- Custom profile file via CLI flag

### Required Operations
- Load and merge profiles
- Auto-detect profiles from repo markers
- Walk repo tree applying all filters
- Detect binary files
- Respect .gitignore
- Report skipped files with reasons

## Changes Made
- Implemented `walker.py` with:
  - `Profile` dataclass and YAML loader
  - `load_bundled_profiles()` — loads all 12 profiles from package
  - `detect_profiles()` — auto-detects from repo root marker files, auto-includes config/devops/web
  - `merge_profiles()` — combines extensions, exclude_dirs, include_patterns from multiple profiles
  - `is_binary()` — extension check + null-byte sniffing (first 8KB)
  - `load_gitignore()` — pathspec-based .gitignore matching
  - `walk_repo()` — full repo traversal with all filters, returns `WalkResult` with files, skipped, profiles_used
  - Falls back to all-text-files mode when no profiles detected
  - Large files are included but flagged in skipped list for chunking
- Added 32 tests in `tests/test_walker.py`
- Fixed pathspec deprecation: `gitwildmatch` → `gitignore`

## Status
✅ Complete

## Notes
- Empty files are skipped (e.g., `__init__.py` with no content)
- Large files are still included in the file list — the analyzer handles chunking
- When no profiles are auto-detected, falls back to all-text-files mode
