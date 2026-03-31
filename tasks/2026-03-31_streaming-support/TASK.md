# Task: Streaming Support

## Summary
Add streaming response support to LLMClient. Streams token-by-token via SSE, which keeps proxy connections alive and avoids Cloudflare 524 timeouts. Should be the default behavior.

## Spec
- LLMClient sends `"stream": true` in requests
- Reads SSE chunks and accumulates the full response
- Works for both OpenAI-compatible (`data: {...}` SSE) and Ollama (newline-delimited JSON) APIs
- Default to streaming; non-streaming as fallback

## Changes Made
- Switched LLMClient to streaming by default (`"stream": true`)
- Added `_read_stream()` supporting both OpenAI SSE and Ollama newline-delimited JSON formats
- Added `on_token` callback parameter threaded through `chat()` → `run_analysis_pass()` → `run_quorum_judge()` → `analyze_file()`
- Added `--show-streaming / --no-show-streaming` CLI flag for live token output
- Fixed HTTP error handling for streaming context (read error body before raising)
- Updated all test mocks to accept `**kwargs` for the new `on_token` parameter

## Status
✅ Complete

## Notes
- Streaming completely eliminates Cloudflare 524 timeouts — tokens keep the connection alive
- Tested against remote LM Studio (lm.mipyip.com): 3/3 files, all high confidence, zero timeouts
- `config.yaml` which previously failed with 524 now passes perfectly with streaming
- Live token output shows all 3 passes (pass1, pass2, quorum judge) inline
