# Task: Analyzer Engine

## Summary
Implement the core analysis pipeline: Ollama HTTP client, two-pass file analysis, quorum judge, retry loop, and JSON parsing. This is the heart of the tool.

## Spec
Per `codebase-analyzer-spec.md`:

### Pipeline per file
1. **Pass 1**: Send file content + analysis prompt to Ollama → get structured JSON
2. **Pass 2**: Same prompt, independent call → get second JSON
3. **Pass 3 (Quorum Judge)**: Send both results to judge prompt → agree/disagree
4. If agree: merge results, mark complete
5. If disagree: retry from pass 1 (up to max_retries, default 3)
6. After max retries: flag for frontier model review

### Ollama HTTP Client
- Use httpx async client against standard Ollama REST API (`/api/chat`)
- Works with any Ollama-compatible endpoint (e.g., LocalLM)
- Exponential backoff on connection failure (1s, 2s, 4s, 8s, max 60s)
- After 5 consecutive connection failures, raise

### JSON Parsing
- LLM returns JSON (sometimes with markdown fencing or preamble)
- Strip markdown fences, extract JSON object
- Retry parse failures (up to 3) — does NOT count against quorum retry limit
- After 3 JSON parse failures on same file, flag with `json_parse_failure`

### Language Detection
- By extension primarily, shebang line as fallback
- Selects appropriate prompt snippet from bundled prompts

### Prompts
- Analysis prompt: system + user template from spec
- Quorum judge prompt: compare two analyses
- Language-specific context injected into system prompt

## Changes Made
- Implemented `analyzer.py` with:
  - Language detection: 60+ extensions, filename matching, shebang detection
  - Prompt snippet loader: maps languages to bundled `.txt` snippets
  - JSON extraction: handles markdown fences, preamble, trailing text, nested objects
  - `OllamaClient`: httpx-based sync client with exponential backoff on connection failures
  - `run_analysis_pass()`: single analysis with JSON parse retry (up to 3, separate from quorum retries)
  - `run_quorum_judge()`: compare two passes, validate verdict has `agree` field
  - `analyze_file()`: full pipeline orchestration — pass1 → pass2 → judge → retry → flag
  - `AnalysisResult` / `AnalysisError` data types
- Added 44 tests in `tests/test_analyzer.py` with mocked Ollama client
- Full test suite: 117 tests passing

## Status
✅ Complete

## Notes
- OllamaClient uses standard `/api/chat` endpoint — works with Ollama, LocalLM, or any compatible API
- JSON parse retries are separate from quorum retries (parse failures don't exhaust quorum attempts)
- The analyzer loop (orchestrating across all files with StateDB) is a separate concern for the CLI wiring task
