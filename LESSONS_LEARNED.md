# Lessons Learned

Patterns, gotchas, anti-patterns, and non-obvious findings. Log anything here that would save time if encountered again.

---

## LM Studio API detection (2026-03-30)

LM Studio responds to Ollama's `/api/tags` endpoint with HTTP 200 but returns `{"error": "Unexpected endpoint or method."}` instead of a valid models list. API auto-detection must validate the response body (check for `"models"` array), not just the status code.

## Context window matters more than model size (2026-03-30)

LM Studio defaults to 4096 context. With our ~500 token system prompt + file content + JSON response, 4096 is far too small for anything beyond trivial files. `package-lock.json` tried to send 118k tokens. **Minimum 8192, recommend 16384+.** This is now documented in README.

## LLM JSON reliability varies wildly (2026-03-30)

First live test at 4096 context: most files got JSON parse failures (empty responses or truncated output). After bumping to 16400 context: 3/3 perfect high-confidence quorum passes. The model can do it — it just needs room to think and respond.

## Per-file error handling is critical (2026-03-30)

One bad file (context too large, model error) was crashing the entire run. API errors like context-length-exceeded must be caught per-file and logged, not propagated as fatal. The tool must keep going — that's the whole point of the resumable architecture.
