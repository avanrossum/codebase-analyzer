# Codebase Analyzer

## Purpose

A language-agnostic Python CLI tool that traverses any codebase, generates structured descriptions of every file using a local LLM via Ollama, validates those descriptions through a quorum process, and outputs 1:1 markdown files suitable for pmem indexing or direct use with Claude Code. Files that fail quorum after retries are flagged for frontier model review. After all individual files are processed, relationship mapping can be performed either via Claude API or by feeding the output to Claude Code manually.

Designed to be open-sourced. No assumptions about language, framework, or codebase structure. Ships with sensible defaults and a profile system for common project types.

## Intended Workflows

1. **Full automation**: Analyze → pmem index → Claude API relationship mapping (all CLI)
2. **Hybrid**: Analyze → pmem index → Claude Code for relationship exploration (interactive)
3. **Manual**: Analyze → browse the markdown files directly → use Claude Code to read them as needed
4. **Minimal**: Analyze only, skip relationship mapping entirely — just get file-level documentation

## Architecture

```
[Repository]
     │
     ▼
[File Walker] ──► [Job Queue (SQLite)] ──► [Analyzer Loop]
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                              [Pass 1: Ollama]        [Pass 2: Ollama]
                                    │                       │
                                    └───────┬───────────────┘
                                            ▼
                                    [Pass 3: Ollama Quorum Judge]
                                            │
                                   ┌────────┴────────┐
                                   ▼                  ▼
                              [Agreed]           [Disagreed]
                                   │                  │
                                   ▼                  ▼
                           [Write .md]      [Retry (up to 3x)]
                                                      │
                                                      ▼
                                              [Still disagreed?]
                                                      │
                                                      ▼
                                              [Flag for Opus]
```

After all files complete:

```
[All .md files + flagged files] ──► [Opus: Relationship Mapping]
                                            │
                                            ▼
                                    [Relationship Map .md]
```

## Job Queue

SQLite database (`analyzer_state.db`) tracking every file through the pipeline.

### Schema

```sql
CREATE TABLE jobs (
    file_path TEXT PRIMARY KEY,       -- relative path from repo root
    status TEXT NOT NULL DEFAULT 'pending',
    -- Status values: pending, pass1_done, pass2_done, quorum_pass,
    --                quorum_fail, retry_1, retry_2, retry_3,
    --                flagged_for_opus, complete
    pass1_result TEXT,                -- JSON: structured analysis from pass 1
    pass2_result TEXT,                -- JSON: structured analysis from pass 2
    quorum_result TEXT,               -- JSON: judge verdict + reasoning
    retry_count INTEGER DEFAULT 0,
    final_description TEXT,           -- agreed-upon markdown content
    error_log TEXT,                   -- accumulated errors if any
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE run_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Stores: repo_path, model_name, started_at, last_resumed_at, etc.
```

### Resume behavior

On startup, the script:

1. Checks if `analyzer_state.db` exists in the output directory
2. If yes, picks up from where it left off — any job not in `complete` or `flagged_for_opus` status gets reprocessed from its current state
3. If no, scans the repo and populates the queue with all eligible files
4. New files found in repo that aren't in the DB get added as `pending`
5. Files in DB but missing from repo get marked as `removed` (not deleted from DB)

## File Walker

### Profile System

The file walker uses profiles to determine which files to include/exclude. Profiles are composable — a project can use multiple profiles.

```yaml
# Built-in profiles ship with the tool
# ~/.codebase-analyzer/profiles/ or bundled in package

# python.yaml
name: python
extensions: [.py, .pyx, .pxd]
include_patterns: ["requirements*.txt", "setup.py", "setup.cfg", "pyproject.toml", "Pipfile", "tox.ini"]
exclude_dirs: ["__pycache__", ".tox", ".eggs", "*.egg-info", "venv", ".venv", "env", ".mypy_cache", ".pytest_cache"]

# javascript.yaml
name: javascript
extensions: [.js, .jsx, .ts, .tsx, .mjs, .cjs]
include_patterns: ["package.json", "tsconfig*.json", ".eslintrc*", "webpack.config.*", "vite.config.*"]
exclude_dirs: ["node_modules", "dist", "build", ".next", "coverage"]

# web.yaml
name: web
extensions: [.html, .css, .scss, .sass, .less, .vue, .svelte]

# config.yaml
name: config
extensions: [.yaml, .yml, .json, .toml, .ini, .cfg, .conf, .env.example]

# devops.yaml
name: devops
extensions: [.sh, .bash, .dockerfile]
include_patterns: ["Dockerfile*", "docker-compose*.yml", "Makefile", "Jenkinsfile", "*.tf", ".github/workflows/*.yml"]

# sql.yaml
name: sql
extensions: [.sql]

# templates.yaml
name: templates
extensions: [.jinja, .jinja2, .mako, .ejs, .hbs, .pug, .erb]

# java.yaml, ruby.yaml, go.yaml, rust.yaml, php.yaml, etc.
```

Usage:

```bash
# Auto-detect profiles based on repo contents (default)
python codebase_analyzer.py /path/to/repo --output ./analysis

# Explicit profiles
python codebase_analyzer.py /path/to/repo --profiles python,web,config,devops

# Custom profile file
python codebase_analyzer.py /path/to/repo --profile-file ./my-project.yaml

# Override: include everything except binary
python codebase_analyzer.py /path/to/repo --all-text-files
```

Auto-detection scans the repo root for markers: `setup.py` → python, `package.json` → javascript, `Gemfile` → ruby, `go.mod` → go, `Cargo.toml` → rust, etc. Multiple profiles activate simultaneously.

### Universal excludes (always applied)

- `.git/`
- Any path matching patterns in `.gitignore` (best effort via pathspec)
- Binary files (detected by file extension AND null-byte sniffing first 8KB)
- Files larger than configurable limit (default 100KB) — logged as skipped with reason

### Large file handling

Files exceeding the context window are split by logical boundaries:

- Language-aware splitting where possible (AST-based for Python, brace-counting for C-family, indentation for YAML)
- Fallback: split by line count with overlap

Each chunk is analyzed independently, then the descriptions are merged in a final local LLM call before entering the quorum process.

## Analysis Prompts

### Language detection

Before analysis, the tool detects the primary language of each file (by extension, shebang line, or content heuristics) and selects the appropriate prompt variant. The JSON schema is consistent across all languages — only the system prompt context changes.

### Pass 1 & 2: File Analysis

The same prompt is used for both passes. The LLM sees only the file content and its path — no information from the other pass.

```
System: You are a senior software developer analyzing a codebase.
The file you are reviewing is written in {detected_language}.
{language_specific_context}
Analyze the provided file and return a JSON object with exactly these fields.
Be precise and specific. Do not speculate about functionality not evident in the code.

Return ONLY valid JSON, no markdown fencing, no preamble.

{
  "purpose": "1-3 sentence description of what this file does",
  "type": "module|class|script|config|template|test|migration|util|interface|unknown",
  "language": "{detected_language}",
  "imports": ["list of imports/includes/requires/use statements"],
  "exports": ["classes, functions, types, or variables this file makes available to other files"],
  "key_classes": [
    {
      "name": "ClassName",
      "purpose": "what it does",
      "methods": ["list of method names"]
    }
  ],
  "key_functions": [
    {
      "name": "function_name",
      "purpose": "what it does"
    }
  ],
  "dependencies": {
    "imports_from": ["local modules/files this file imports from"],
    "imported_by_hint": "any clues about what might use this (e.g., route registration, plugin hooks, event handlers, DI bindings)"
  },
  "language_specific_notes": "notable language-version or framework-specific patterns (e.g., Python 2 unicode handling, legacy React class components, CommonJS vs ESM)",
  "side_effects": "any module-level side effects (DB connections, monkey-patching, signal handlers, global state mutation, auto-registration)",
  "complexity_notes": "anything that makes this file particularly complex or fragile"
}

User: File: {relative_path}

```
{file_content}
```
```

#### Language-specific context snippets (injected into `{language_specific_context}`)

These ship as editable templates in `~/.codebase-analyzer/prompts/` or bundled defaults:

- **Python**: "Pay attention to Python version indicators (__future__ imports, print statements vs functions, type hints). Note any use of metaclasses, descriptors, or monkey-patching."
- **JavaScript/TypeScript**: "Note module system (CommonJS require vs ESM import). Identify framework patterns (React hooks/components, Express middleware, Vue composition API). Flag any dynamic imports or eval usage."
- **Java**: "Identify design patterns (Factory, Singleton, Observer). Note Spring/Jakarta annotations, interface implementations, and inheritance hierarchies."
- **Go**: "Note goroutine usage, channel patterns, interface satisfaction. Identify any init() functions and their side effects."
- **Ruby**: "Note metaprogramming (method_missing, define_method), DSL patterns, mixin usage. Identify Rails conventions if present."
- **Config/YAML/JSON**: "Describe what this configuration controls, what system or service consumes it, and any environment-specific overrides."
- **SQL**: "Describe what tables/views/functions this creates or modifies, any migrations it performs, and notable constraints or indexes."
- **Shell**: "Describe what this script automates, what it depends on, and any assumptions about the environment."

Users can add custom snippets for niche languages or frameworks.

### Pass 3: Quorum Judge

```
System: You are comparing two independent analyses of the same source file.
Your job is to determine whether the two analyses substantially agree on
what this file does. Minor wording differences are fine. Disagreements on
purpose, type, key functionality, or dependencies are NOT fine.

Return ONLY valid JSON:

{
  "agree": true|false,
  "merged_result": { ... },  // If agree=true: best-of-both merged analysis
  "disagreements": ["list of specific disagreements"],  // If agree=false
  "confidence": "high|medium|low"
}

If agree=true, produce a merged_result that takes the best/most complete
information from both analyses. Prefer specificity over vagueness.

If agree=false, list the specific points of disagreement so they can be
resolved on retry.

User: File: {relative_path}

Analysis 1:
```json
{pass1_json}
```

Analysis 2:
```json
{pass2_json}
```
```

## Retry Logic

When quorum fails:

1. Log the specific disagreements from the judge
2. Increment `retry_count`
3. If `retry_count < 3`: re-enter the pipeline at pass 1 (both passes re-run fresh)
4. If `retry_count >= 3`: set status to `flagged_for_opus`, store all accumulated results and disagreement history in `error_log`

Flagged files are collected at the end for batch Opus review.

## Output Format

### Per-file markdown (1:1 mapping)

Output directory mirrors the repo structure:

```
output/
  files/
    path/
      to/
        module.py.md
        other_file.py.md
  flagged/
    path/
      to/
        problematic_file.py.json   # full analysis history for Opus
  relationships/
    _index.md                       # master relationship map (from Opus)
    module_map.md                   # by-module breakdown
  analyzer_state.db
  run_report.md                     # summary stats
```

### Individual file markdown format

Keep it concise. pmem works best when content under each heading is brief — aim for 2-5 lines per section max. Omit sections that are empty or not applicable rather than including "None" entries.

```markdown
# {relative_path}

**Type:** {type} | **Language:** {language}

## Purpose

{purpose}

## Key Classes

- **{ClassName}**: {purpose}
  - Methods: {method1}, {method2}, {method3}

## Key Functions

- **{function_name}**: {purpose}

## Dependencies

- **Imports from:** {local_module_1}, {local_module_2}
- **Imported by (hint):** {hint}

## Side Effects

{side_effects}

## Language-Specific Notes

{language_specific_notes}

## Complexity Notes

{complexity_notes}
```

## Relationship Mapping (Phase 2)

Relationship mapping is a separate phase that runs after all individual files are analyzed. It can be performed in three ways:

### Option A: Claude API (automated)

Run via CLI. The tool batches file descriptions and sends them to the Claude API for synthesis. This is the fully automated path.

```bash
python codebase_analyzer.py --relationships ./analysis_output \
  --api-key $ANTHROPIC_API_KEY \
  --relationship-model claude-sonnet-4-20250514
```

### Option B: Claude Code (interactive)

The tool generates a structured prompt file that can be fed to Claude Code. This lets you use Claude Code's codebase awareness and interactive refinement.

```bash
# Generate the relationship prompt file
python codebase_analyzer.py --relationships ./analysis_output --export-prompt

# This creates: output/relationships/_relationship_prompt.md
# Then in Claude Code: "Read output/relationships/_relationship_prompt.md and follow the instructions"
```

The exported prompt includes all file descriptions organized by module, plus instructions for what to produce. The user drives the conversation from there.

### Option C: Skip it

Just use the per-file markdown as-is. Index it with pmem, let Claude Code discover relationships organically as needed. Costs more tokens over time but zero upfront relationship mapping cost.

### What relationship mapping produces

Regardless of which option is used, the expected output is:

1. **Module-level relationship map**: how top-level directories/packages relate to each other
2. **Dependency graph**: which modules depend on which (directional)
3. **Entry points**: where execution begins (main scripts, web server entry, CLI commands, task runners)
4. **Shared state**: global state, singletons, or shared resources that create implicit coupling
5. **Circular dependencies**: any detected circular import/require chains
6. **Plugin/extension points**: how the codebase discovers, registers, or loads dynamic components (if applicable)
7. **Architecture summary**: a plain-English overview of the system architecture suitable for onboarding a new developer

The relationship map is the high-value output. Individual file analysis is grunt work for the local model; the relationship synthesis is where frontier reasoning earns its cost.

### Flagged file resolution

Files that failed quorum can also be resolved in three ways:

```bash
# Via Claude API
python codebase_analyzer.py --resolve-flagged ./analysis_output \
  --api-key $ANTHROPIC_API_KEY

# Export for Claude Code
python codebase_analyzer.py --resolve-flagged ./analysis_output --export-prompt

# Manually review the flagged/ directory and write the .md files yourself
```

### API batching strategy

When using Claude API for relationships:

- Group files by top-level directory/module (natural code boundaries)
- Each batch: send the markdown descriptions for one module + a list of cross-module imports detected in that module
- Final synthesis batch: send all module-level summaries for the global relationship map
- Target: keep each API call under 100k tokens input to stay within context window comfortably

## CLI Interface

```bash
# Initial run (auto-detects language profiles)
python codebase_analyzer.py /path/to/repo --output ./analysis_output

# Resume interrupted run (detects existing state.db automatically)
python codebase_analyzer.py /path/to/repo --output ./analysis_output

# Explicit language profiles
python codebase_analyzer.py /path/to/repo --output ./analysis_output \
  --profiles python,web,config

# Check progress
python codebase_analyzer.py --status ./analysis_output

# Relationship mapping via Claude API
python codebase_analyzer.py --relationships ./analysis_output \
  --api-key $ANTHROPIC_API_KEY \
  --relationship-model claude-sonnet-4-20250514

# Export relationship prompt for Claude Code
python codebase_analyzer.py --relationships ./analysis_output --export-prompt

# Resolve flagged files via API
python codebase_analyzer.py --resolve-flagged ./analysis_output \
  --api-key $ANTHROPIC_API_KEY

# Export flagged files for Claude Code
python codebase_analyzer.py --resolve-flagged ./analysis_output --export-prompt

# Override defaults
python codebase_analyzer.py /path/to/repo \
  --output ./analysis_output \
  --model qwen3:32b-q5_K_M \
  --ollama-url http://localhost:11434 \
  --max-retries 3 \
  --max-file-size 100000 \
  --concurrency 1 \
  --api-key $ANTHROPIC_API_KEY \
  --api-batch-size 50
```

## Configuration

Stored in `run_metadata` table and/or a `config.yaml` in the output directory:

```yaml
repo_path: /path/to/repo
model: qwen3:32b-q5_K_M
ollama_url: http://localhost:11434
max_retries: 3
max_file_size: 100000        # bytes, files larger than this get chunked
concurrency: 1               # parallel Ollama requests (1 is safest for single-GPU)
profiles: auto               # auto-detect, or list: [python, web, config]
api_model: claude-sonnet-4-20250514   # for relationship mapping + flagged resolution
api_batch_size: 50           # files per relationship API call
exclude_patterns:            # additional excludes beyond profile defaults
  - "*/migrations/*"
  - "*/fixtures/*"
  - "*/vendor/*"
```

## Progress & Reporting

### Live progress (stdout)

```
[1247/3012] analyzing: widgets/core/renderer.py (pass 1)
[1247/3012] analyzing: widgets/core/renderer.py (pass 2)
[1247/3012] quorum: AGREE (high confidence)
[1247/3012] ✓ written: output/files/widgets/core/renderer.py.md

[1248/3012] analyzing: widgets/core/registry.py (pass 1)
...

[RETRY 1/3] widgets/legacy/compat.py — disagreement on: purpose, side_effects
```

### Run report (generated on completion or interrupt)

```markdown
# Codebase Analysis Run Report

- **Repository:** /path/to/repo
- **Model:** qwen3:32b-q5_K_M
- **Started:** 2026-03-29T20:00:00
- **Completed:** 2026-03-30T08:00:00
- **Duration:** 12h 00m

## Progress

- Total files: 3,012
- Completed (quorum pass): 2,891 (95.9%)
- Flagged for Opus: 47 (1.6%)
- Skipped (too large / binary): 74 (2.5%)
- Errors: 0

## Quorum Stats

- First-pass agreement: 2,654 (88.1%)
- Required 1 retry: 187 (6.2%)
- Required 2 retries: 42 (1.4%)
- Required 3 retries: 8 (0.3%)
- Failed all retries: 47 (1.6%)

## Flagged Files

| File | Disagreement Summary |
|------|---------------------|
| widgets/legacy/compat.py | Conflicting purpose: "compatibility layer" vs "runtime patcher" |
| ... | ... |
```

## Error Handling

- **Ollama connection failure**: retry with exponential backoff (1s, 2s, 4s, 8s, max 60s). After 5 consecutive connection failures, pause and prompt user (or exit with resume state saved).
- **Malformed JSON from LLM**: retry that specific pass (does not count against quorum retry limit). After 3 JSON parse failures on the same file, flag for Opus with `json_parse_failure` in error_log.
- **File read errors**: log and skip, mark as `error` in DB.
- **Opus API errors**: retry with backoff. Rate limit errors pause for the indicated duration.
- **Keyboard interrupt (Ctrl+C)**: graceful shutdown — finish current file, save state, write interim report.

## Dependencies

```
httpx          # async HTTP client for Ollama API
anthropic      # Claude API client (optional — only needed for API-based relationship mapping)
click          # CLI framework
rich           # progress display and tables
pyyaml         # config files
pathspec       # .gitignore pattern matching
```

`anthropic` is an optional dependency. The tool should work fully for Phase 1 (file analysis) with only Ollama. Claude API is only required if the user wants automated relationship mapping or flagged file resolution via API.

## Packaging & Distribution

- PyPI package: `codebase-analyzer` (or similar available name)
- Entry point: `codebase-analyzer` CLI command after `pip install`
- License: MIT
- Repo structure:

```
codebase-analyzer/
  src/
    codebase_analyzer/
      __init__.py
      cli.py              # click CLI
      walker.py            # file discovery + profile system
      analyzer.py          # Ollama analysis + quorum logic
      relationships.py     # Claude API + prompt export
      state.py             # SQLite job queue
      output.py            # markdown generation
      profiles/            # bundled language profiles (yaml)
      prompts/             # bundled language-specific prompt snippets
  tests/
  README.md
  pyproject.toml
```

## Future Considerations

- **Incremental updates**: re-analyze only files changed since last run (git diff integration)
- **pmem direct integration**: output directly to pmem index format once language-aware chunking lands
- **Parallel analysis**: if moving to a faster machine or external GPU, support concurrent Ollama requests
- **Community profiles**: accept PRs for language/framework profiles (Elixir, Kotlin, Swift, etc.)
- **Embedding generation**: optionally generate embeddings alongside descriptions for semantic search
- **OpenAI-compatible API support**: allow any OpenAI-compatible endpoint as the local model backend (not just Ollama) — LM Studio, vLLM, llama.cpp server, etc.
- **CI integration**: run as a GitHub Action on PRs to keep documentation in sync with code changes
