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
*To be updated as work proceeds.*

## Status
🔵 In Progress

## Notes
- Entry point: `codebase-analyzer` CLI command via `pyproject.toml` `[project.scripts]`
- `anthropic` must be an optional dependency — the tool works fully without it
