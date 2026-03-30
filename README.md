# Codebase Analyzer

A language-agnostic CLI tool that traverses any codebase, generates structured descriptions of every file using a local LLM via [Ollama](https://ollama.com), validates those descriptions through a quorum process, and outputs 1:1 markdown files.

## Features

- **Language-agnostic** — ships with profiles for Python, JavaScript/TypeScript, Java, Go, Ruby, Rust, PHP, and more
- **Local-first** — uses Ollama for all file analysis, no API keys required for core functionality
- **Quorum validation** — two independent LLM passes with a judge pass to ensure accuracy
- **Resumable** — SQLite-backed state means you can stop and resume at any time
- **Relationship mapping** — optional frontier model integration for cross-file dependency analysis

## Installation

```bash
pip install codebase-analyzer
```

For development:

```bash
git clone https://github.com/avanrossum/codebase-analyzer.git
cd codebase-analyzer
pip install -e ".[dev]"
```

## Prerequisites

- Python 3.9+
- A local LLM server running with a capable model. Supported backends:
  - [Ollama](https://ollama.com) (default, uses `/api/chat`)
  - [LM Studio](https://lmstudio.ai) (uses OpenAI-compatible `/v1/chat/completions`)
  - Any OpenAI-compatible API (vLLM, llama.cpp server, etc.)

### Model Requirements

- **Context window: 8192 tokens minimum, 16384+ recommended.** The tool sends a ~500 token system prompt plus the full file content, and the model must generate a structured JSON response. Files that exceed the context window will error and be skipped.
- **JSON output quality matters.** The model must reliably produce valid JSON. Larger models (30B+) perform significantly better at this than smaller ones.
- Default model: `qwen3:32b-q5_K_M` (Ollama). Override with `--model`.

### Performance Notes

- Each file requires **3 LLM calls minimum** (two analysis passes + one quorum judge), plus retries on disagreement. A 100-file repo means 300+ inference calls.
- Default concurrency is 1 (single-GPU safe). For multi-GPU setups, increase with `--concurrency`.
- Large codebases can take hours on consumer hardware. The tool is fully resumable — stop and restart at any time.

## Quick Start

```bash
# Analyze a repository (auto-detects language profiles)
codebase-analyzer analyze /path/to/repo --output ./analysis

# Check progress
codebase-analyzer status ./analysis

# Resume an interrupted run (just re-run the same command)
codebase-analyzer analyze /path/to/repo --output ./analysis
```

## Usage

### Analyze

```bash
# Explicit language profiles
codebase-analyzer analyze /path/to/repo --output ./analysis --profiles python,web,config

# Custom profile file
codebase-analyzer analyze /path/to/repo --output ./analysis --profile-file ./my-project.yaml

# Include all text files
codebase-analyzer analyze /path/to/repo --output ./analysis --all-text-files

# Override model and concurrency
codebase-analyzer analyze /path/to/repo --output ./analysis \
  --model qwen3:32b-q5_K_M \
  --ollama-url http://localhost:11434 \
  --max-retries 3 \
  --max-file-size 100000 \
  --concurrency 1
```

### Relationship Mapping

After analysis completes, optionally map cross-file relationships:

```bash
# Via Claude API (automated)
codebase-analyzer relationships ./analysis --api-key $ANTHROPIC_API_KEY

# Export prompt for Claude Code (interactive)
codebase-analyzer relationships ./analysis --export-prompt
```

### Resolve Flagged Files

Files that fail quorum after retries can be resolved with a frontier model:

```bash
# Via Claude API
codebase-analyzer resolve-flagged ./analysis --api-key $ANTHROPIC_API_KEY

# Export for manual review
codebase-analyzer resolve-flagged ./analysis --export-prompt
```

## Output Structure

```
analysis/
  files/                    # 1:1 markdown files mirroring repo structure
    path/to/module.py.md
  flagged/                  # files that failed quorum (JSON with full history)
    path/to/problem.py.json
  relationships/            # cross-file dependency maps (if generated)
    _index.md
    module_map.md
  analyzer_state.db         # SQLite state for resume capability
  run_report.md             # summary statistics
```

## Optional Dependencies

The core analysis pipeline requires only Ollama. For automated relationship mapping and flagged file resolution via Claude API:

```bash
pip install "codebase-analyzer[api]"
```

## License

MIT
