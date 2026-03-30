# Changelog

All notable changes to this project are documented here.

Format: entries grouped by date, with bullet points describing what changed.

---

## [2026-03-30] — v0.1.0: Initial Working Release

- Project scaffolding: pyproject.toml, CLI entry point, 12 language profiles, 8 prompt snippets
- SQLite state layer: job queue with resume support, progress tracking
- File walker: profile-based discovery, auto-detection, .gitignore support, binary detection
- Analyzer engine: LLM client with auto-detection (Ollama + OpenAI-compatible APIs), two-pass analysis, quorum judge, retry-then-flag pipeline
- Output generation: per-file markdown, flagged file JSON, run report with stats
- CLI wiring: full pipeline integration, Rich progress display, graceful Ctrl+C shutdown
- Live tested against LM Studio + qwen3.5-35b-a3b: 3/3 files, 100% quorum pass
- 143 tests passing

---

## [2026-03-30] — Task Governance Initialized

- Created `TASKS.md` task tracker
- Created `tasks/` directory for task folders
- Created `ROADMAP.md` for priority tracking
- Created `LESSONS_LEARNED.md` for institutional knowledge
- Added task conventions and coding standards to `CLAUDE.md`
- `CLAUDE.md` excluded from git (local governance only, not shipped with open source)
