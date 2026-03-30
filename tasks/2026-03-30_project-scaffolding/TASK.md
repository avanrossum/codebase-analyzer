# Task: Project Scaffolding

## Summary
Stand up the Python package structure so `codebase-analyzer` can be installed and its CLI invoked. This is the skeleton that all subsequent tasks build on.

## Spec
Per `codebase-analyzer-spec.md`, create:

- `pyproject.toml` — package metadata, dependencies, entry point
  - Required: `httpx`, `click`, `rich`, `pyyaml`, `pathspec`
  - Optional: `anthropic` (only for relationship mapping / flagged file resolution)
- `src/codebase_analyzer/` package with module stubs:
  - `__init__.py`
  - `cli.py` — Click CLI with all flags from spec (no-op implementations)
  - `walker.py` — file discovery + profile system
  - `analyzer.py` — Ollama analysis + quorum logic
  - `relationships.py` — Claude API + prompt export
  - `state.py` — SQLite job queue
  - `output.py` — markdown generation
- `src/codebase_analyzer/profiles/` — bundled language profiles (YAML)
- `src/codebase_analyzer/prompts/` — bundled language-specific prompt snippets
- `tests/` directory with initial structure
- `README.md` — basic project description, installation, usage

Goal: `pip install -e .` works, `codebase-analyzer --help` shows all commands/flags.

## Changes Made
- Created `pyproject.toml` with hatchling build, all dependencies, optional `[api]` extra for anthropic
- Created `src/codebase_analyzer/` package with `__init__.py`, `cli.py`, `walker.py`, `analyzer.py`, `relationships.py`, `state.py`, `output.py`
- Created `cli.py` with Click group and 4 subcommands: `analyze`, `status`, `relationships`, `resolve-flagged` — all flags from spec wired up
- Created 12 bundled language profiles (YAML): python, javascript, web, config, devops, sql, templates, java, ruby, go, rust, php
- Created 8 prompt snippets: python, javascript, java, go, ruby, config, sql, shell
- Created `tests/test_cli.py` with 6 smoke tests (all passing)
- Created `README.md` with installation, usage, and output structure docs
- Updated `.gitignore` with Python/IDE/OS patterns

## Status
✅ Complete

## Notes
- Entry point: `codebase-analyzer` CLI command via `pyproject.toml` `[project.scripts]`
- `anthropic` is an optional dependency under `[api]` extra — core tool works without it
- Used Click group with subcommands rather than mode flags — cleaner CLI ergonomics
- venv at `.venv/` — `source .venv/bin/activate` to use
