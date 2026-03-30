# Task: Output Generation

## Summary
Implement markdown generation from analysis results and the run report. Converts merged analysis JSON into per-file `.md` files and generates summary statistics.

## Spec
Per `codebase-analyzer-spec.md`:

### Output directory structure
```
output/
  files/           # 1:1 markdown mirroring repo structure
  flagged/         # full analysis history for files that failed quorum
  relationships/   # populated by Phase 2
  analyzer_state.db
  run_report.md
```

### Per-file markdown format
Concise, omit empty sections. Headings: Purpose, Key Classes, Key Functions, Dependencies, Side Effects, Language-Specific Notes, Complexity Notes.

### Flagged file output
JSON with full analysis history (all pass results, disagreements, error log).

### Run report
Summary stats: total files, completion rate, quorum stats, flagged files list.

## Changes Made
- Implemented `output.py` with:
  - `ensure_output_dirs()` — creates files/, flagged/, relationships/ subdirs
  - `write_file_markdown()` — per-file markdown from merged analysis, omits empty/None sections
  - `write_flagged_file()` — full analysis history as JSON for flagged files
  - `generate_run_report()` — run stats, quorum breakdown, flagged files table, duration calc
- Added 20 tests in `tests/test_output.py`

## Status
✅ Complete

## Notes
- Sections with value "None" or "N/A" are omitted from markdown output
- Flagged file JSON includes parsed pass results (not raw strings)
- Run report calculates retry distribution from completed jobs' retry_count
