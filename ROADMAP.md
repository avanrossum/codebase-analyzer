# Roadmap

> Last updated: 2026-03-31

---

## Current Priorities

- [ ] Large file chunking (files exceeding LLM context window)
- [ ] Live test against legacy Py2 + React monolith on Mac Studio
- [ ] `relationships.py` — Claude API relationship mapping + prompt export
- [ ] `resolve-flagged` command — frontier model resolution

---

## Backlog

- [ ] Incremental updates: re-analyze only files changed since last run (git diff integration)
- [ ] Parallel analysis: concurrent Ollama requests for multi-GPU setups
- [ ] Community profiles: Elixir, Kotlin, Swift, etc.
- [ ] Embedding generation alongside descriptions for semantic search
- [ ] OpenAI-compatible API as alternative local backend (partially done — LLMClient supports it)
- [ ] CI integration: GitHub Action to keep documentation in sync with code changes
- [ ] User-configurable prompt snippets from `~/.codebase-analyzer/prompts/`

---

## Completed

- [x] Task governance infrastructure
- [x] Project scaffolding (pyproject.toml, CLI, profiles, prompts)
- [x] SQLite state layer with resume support
- [x] File walker with profile system and .gitignore support
- [x] Analyzer engine with two-pass quorum pipeline
- [x] Output generation (markdown, flagged JSON, run report)
- [x] CLI wiring with Rich progress and graceful Ctrl+C
- [x] OpenAI-compatible API support (LM Studio, vLLM, etc.)
- [x] Live test: 3/3 files, 100% quorum pass (LM Studio + qwen3.5-35b-a3b)
- [x] Published to GitHub (avanrossum/codebase-analyzer)
