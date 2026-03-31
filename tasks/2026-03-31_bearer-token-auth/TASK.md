# Task: Bearer Token Auth

## Summary
Add bearer token authentication to LLMClient for remote LLM endpoints that require it (e.g., LM Studio behind auth).

## Spec
- New `--api-token` CLI flag (also reads `LLM_API_TOKEN` env var)
- LLMClient sends `Authorization: Bearer <token>` header on all requests when token is provided
- Works for both API detection probes and chat requests

## Changes Made
- Added `api_token` parameter to `LLMClient.__init__()` — sets `Authorization: Bearer` header on the httpx client
- Added `--api-token` CLI flag to `analyze` command (also reads `LLM_API_TOKEN` env var)
- Header applies to all requests (detection probes + chat calls)

## Status
✅ Complete

## Notes
- Token is set at httpx Client level so it covers all requests automatically
- User's remote setup: lm.mipyip.com, Qwen3.5-35b MTX, 65k context, M1 Studio
