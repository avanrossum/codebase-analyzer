# Task: SQLite State Layer

## Summary
Implement the SQLite job queue that tracks every file through the analysis pipeline. This is the foundation for resume capability and progress tracking — every other module depends on it.

## Spec
Per `codebase-analyzer-spec.md`:

### Schema
- `jobs` table: `file_path` (PK), `status`, `pass1_result`, `pass2_result`, `quorum_result`, `retry_count`, `final_description`, `error_log`, `created_at`, `updated_at`
- `run_metadata` table: key-value store for `repo_path`, `model_name`, `started_at`, `last_resumed_at`, etc.
- Status values: `pending`, `pass1_done`, `pass2_done`, `quorum_pass`, `quorum_fail`, `retry_1`, `retry_2`, `retry_3`, `flagged_for_opus`, `complete`, `error`, `removed`

### Resume Behavior
1. Check if `analyzer_state.db` exists in the output directory
2. If yes, pick up from where it left off — any job not in `complete` or `flagged_for_opus` gets reprocessed from its current state
3. If no, create fresh DB
4. New files found in repo that aren't in the DB get added as `pending`
5. Files in DB but missing from repo get marked as `removed`

### Required Operations
- Initialize/open database
- Add jobs (batch insert for initial scan)
- Update job status and results at each pipeline stage
- Query jobs by status (for the analyzer loop)
- Get/set run metadata
- Progress stats (counts by status for reporting)
- Mark missing files as `removed`

## Changes Made
- Implemented `StateDB` class in `src/codebase_analyzer/state.py` with:
  - `jobs` table with full schema from spec (file_path PK, status, pass results, retry_count, etc.)
  - `run_metadata` key-value table
  - `add_jobs()` — batch insert with duplicate skipping
  - `update_status()` — status + field updates with validation, auto JSON serialization
  - `get_job()`, `get_jobs_by_status()`, `get_resumable_jobs()` — query methods
  - `get_all_tracked_paths()`, `mark_removed()` — for resume/sync with repo
  - `get_progress()`, `get_total_counts()` — progress stats
  - `set_metadata()`, `get_metadata()`, `get_all_metadata()` — run config
  - Context manager support, WAL journal mode
- Added 35 tests in `tests/test_state.py` covering all operations, edge cases, and full pipeline simulation

## Status
✅ Complete

## Notes
- Used WAL journal mode for better read concurrency even though default concurrency is 1
- Resumable jobs are ordered by pipeline stage (pending first, then pass1_done, etc.)
- JSON result fields accept both dicts (auto-serialized) and raw strings
- Status values are validated against a known set; unknown fields raise ValueError
