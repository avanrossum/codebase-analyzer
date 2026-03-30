"""Ollama analysis engine and quorum logic."""

import importlib.resources
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

# -- Language detection --

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".pyx": "Python", ".pxd": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".go": "Go",
    ".rb": "Ruby", ".rake": "Ruby", ".gemspec": "Ruby",
    ".rs": "Rust",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cxx": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".scala": "Scala",
    ".r": "R", ".R": "R",
    ".lua": "Lua",
    ".pl": "Perl", ".pm": "Perl",
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hrl": "Erlang",
    ".hs": "Haskell",
    ".clj": "Clojure", ".cljs": "Clojure",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".sql": "SQL",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".ini": "INI", ".cfg": "INI", ".conf": "INI",
    ".xml": "XML",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "SASS", ".less": "LESS",
    ".md": "Markdown", ".rst": "reStructuredText",
    ".dockerfile": "Dockerfile",
    ".tf": "Terraform",
    ".jinja": "Jinja", ".jinja2": "Jinja",
    ".mako": "Mako",
    ".ejs": "EJS",
    ".hbs": "Handlebars",
    ".pug": "Pug",
    ".erb": "ERB",
}

SHEBANG_PATTERNS: list[tuple[str, str]] = [
    ("python", "Python"),
    ("ruby", "Ruby"),
    ("node", "JavaScript"),
    ("bash", "Shell"),
    ("sh", "Shell"),
    ("zsh", "Shell"),
    ("perl", "Perl"),
    ("php", "PHP"),
]

# Map languages to their prompt snippet file
LANGUAGE_TO_PROMPT: dict[str, str] = {
    "Python": "python",
    "JavaScript": "javascript", "TypeScript": "javascript",
    "Java": "java", "Kotlin": "java",
    "Go": "go",
    "Ruby": "ruby",
    "YAML": "config", "JSON": "config", "TOML": "config",
    "INI": "config", "XML": "config",
    "SQL": "sql",
    "Shell": "shell",
}

JSON_PARSE_MAX_RETRIES = 3
CONNECTION_MAX_RETRIES = 5
CONNECTION_BACKOFF_BASE = 1
CONNECTION_BACKOFF_MAX = 60


def detect_language(file_path: str, content: str = "") -> str:
    """Detect the programming language of a file."""
    _, ext = os.path.splitext(file_path)
    if ext.lower() in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext.lower()]

    # Check for specific filenames
    basename = os.path.basename(file_path)
    name_map = {
        "Dockerfile": "Dockerfile",
        "Makefile": "Shell",
        "Jenkinsfile": "Groovy",
        "Gemfile": "Ruby",
        "Rakefile": "Ruby",
        "Vagrantfile": "Ruby",
    }
    if basename in name_map:
        return name_map[basename]

    # Check shebang
    if content:
        first_line = content.split("\n", 1)[0]
        if first_line.startswith("#!"):
            for pattern, lang in SHEBANG_PATTERNS:
                if pattern in first_line:
                    return lang

    return "Unknown"


def load_prompt_snippet(language: str) -> str:
    """Load the language-specific prompt context snippet."""
    prompt_key = LANGUAGE_TO_PROMPT.get(language)
    if not prompt_key:
        return ""

    prompts_dir = importlib.resources.files("codebase_analyzer") / "prompts"
    prompt_file = prompts_dir / f"{prompt_key}.txt"

    try:
        return prompt_file.read_text().strip()
    except (FileNotFoundError, OSError):
        return ""


# -- Prompt templates --

ANALYSIS_SYSTEM_PROMPT = """\
You are a senior software developer analyzing a codebase.
The file you are reviewing is written in {language}.
{language_context}
Analyze the provided file and return a JSON object with exactly these fields.
Be precise and specific. Do not speculate about functionality not evident in the code.

Return ONLY valid JSON, no markdown fencing, no preamble.

{{
  "purpose": "1-3 sentence description of what this file does",
  "type": "module|class|script|config|template|test|migration|util|interface|unknown",
  "language": "{language}",
  "imports": ["list of imports/includes/requires/use statements"],
  "exports": ["classes, functions, types, or variables this file makes available to other files"],
  "key_classes": [
    {{
      "name": "ClassName",
      "purpose": "what it does",
      "methods": ["list of method names"]
    }}
  ],
  "key_functions": [
    {{
      "name": "function_name",
      "purpose": "what it does"
    }}
  ],
  "dependencies": {{
    "imports_from": ["local modules/files this file imports from"],
    "imported_by_hint": "any clues about what might use this (e.g., route registration, plugin hooks, event handlers, DI bindings)"
  }},
  "language_specific_notes": "notable language-version or framework-specific patterns",
  "side_effects": "any module-level side effects (DB connections, monkey-patching, signal handlers, global state mutation, auto-registration)",
  "complexity_notes": "anything that makes this file particularly complex or fragile"
}}"""

ANALYSIS_USER_PROMPT = """\
File: {file_path}

```
{file_content}
```"""

QUORUM_SYSTEM_PROMPT = """\
You are comparing two independent analyses of the same source file.
Your job is to determine whether the two analyses substantially agree on
what this file does. Minor wording differences are fine. Disagreements on
purpose, type, key functionality, or dependencies are NOT fine.

Return ONLY valid JSON:

{
  "agree": true|false,
  "merged_result": { ... },
  "disagreements": ["list of specific disagreements"],
  "confidence": "high|medium|low"
}

If agree=true, produce a merged_result that takes the best/most complete
information from both analyses. Prefer specificity over vagueness.

If agree=false, list the specific points of disagreement so they can be
resolved on retry."""

QUORUM_USER_PROMPT = """\
File: {file_path}

Analysis 1:
```json
{pass1_json}
```

Analysis 2:
```json
{pass2_json}
```"""


# -- JSON extraction --

def extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output, handling markdown fencing and preamble."""
    # Strip markdown code fences
    text = text.strip()

    # Try to find JSON in code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find a JSON object by braces
    brace_start = text.find("{")
    if brace_start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    # Find matching closing brace
    depth = 0
    in_string = False
    escape_next = False
    for i in range(brace_start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start:i + 1])

    # Fall back to plain parse
    return json.loads(text[brace_start:])


# -- Ollama client --

class OllamaClient:
    """HTTP client for the Ollama-compatible API."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:32b-q5_K_M"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=300.0)
        self._consecutive_failures = 0

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def chat(self, system: str, user: str) -> str:
        """Send a chat completion request and return the response text.

        Implements exponential backoff on connection failures.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }

        backoff = CONNECTION_BACKOFF_BASE
        for attempt in range(CONNECTION_MAX_RETRIES):
            try:
                response = self._client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                self._consecutive_failures = 0
                data = response.json()
                return data["message"]["content"]
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                self._consecutive_failures += 1
                if self._consecutive_failures >= CONNECTION_MAX_RETRIES:
                    raise ConnectionError(
                        f"Ollama unavailable after {CONNECTION_MAX_RETRIES} consecutive failures: {e}"
                    ) from e
                log.warning(
                    "Ollama connection failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1, CONNECTION_MAX_RETRIES, backoff, e,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, CONNECTION_BACKOFF_MAX)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"Ollama API error ({e.response.status_code}): {e.response.text}"
                ) from e

        raise ConnectionError(f"Ollama unavailable after {CONNECTION_MAX_RETRIES} attempts")


# -- Analysis pipeline --

def build_analysis_prompt(file_path: str, file_content: str, language: str) -> tuple[str, str]:
    """Build the system and user prompts for file analysis."""
    context = load_prompt_snippet(language)
    system = ANALYSIS_SYSTEM_PROMPT.format(language=language, language_context=context)
    user = ANALYSIS_USER_PROMPT.format(file_path=file_path, file_content=file_content)
    return system, user


def build_quorum_prompt(file_path: str, pass1: dict, pass2: dict) -> tuple[str, str]:
    """Build the system and user prompts for quorum judging."""
    user = QUORUM_USER_PROMPT.format(
        file_path=file_path,
        pass1_json=json.dumps(pass1, indent=2),
        pass2_json=json.dumps(pass2, indent=2),
    )
    return QUORUM_SYSTEM_PROMPT, user


def run_analysis_pass(client: OllamaClient, file_path: str, file_content: str, language: str) -> dict:
    """Run a single analysis pass with JSON parse retry.

    Returns the parsed JSON result.
    Raises AnalysisError if JSON parsing fails after retries.
    """
    system, user = build_analysis_prompt(file_path, file_content, language)

    for attempt in range(JSON_PARSE_MAX_RETRIES):
        raw = client.chat(system, user)
        try:
            return extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(
                "JSON parse failure on %s (attempt %d/%d): %s",
                file_path, attempt + 1, JSON_PARSE_MAX_RETRIES, e,
            )
            if attempt == JSON_PARSE_MAX_RETRIES - 1:
                raise AnalysisError(
                    f"JSON parse failure after {JSON_PARSE_MAX_RETRIES} attempts",
                    file_path=file_path,
                    raw_output=raw,
                ) from e

    # Unreachable but satisfies type checkers
    raise AnalysisError("JSON parse failure", file_path=file_path)


def run_quorum_judge(client: OllamaClient, file_path: str, pass1: dict, pass2: dict) -> dict:
    """Run the quorum judge to compare two analysis passes.

    Returns the parsed judge verdict with keys: agree, merged_result/disagreements, confidence.
    Raises AnalysisError if JSON parsing fails after retries.
    """
    system, user = build_quorum_prompt(file_path, pass1, pass2)

    for attempt in range(JSON_PARSE_MAX_RETRIES):
        raw = client.chat(system, user)
        try:
            result = extract_json(raw)
            # Validate expected fields
            if "agree" not in result:
                raise ValueError("Judge response missing 'agree' field")
            return result
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(
                "Quorum judge JSON failure on %s (attempt %d/%d): %s",
                file_path, attempt + 1, JSON_PARSE_MAX_RETRIES, e,
            )
            if attempt == JSON_PARSE_MAX_RETRIES - 1:
                raise AnalysisError(
                    f"Quorum judge JSON failure after {JSON_PARSE_MAX_RETRIES} attempts",
                    file_path=file_path,
                    raw_output=raw,
                ) from e

    raise AnalysisError("Quorum judge failure", file_path=file_path)


def analyze_file(
    client: OllamaClient,
    file_path: str,
    file_content: str,
    max_retries: int = 3,
) -> "AnalysisResult":
    """Run the full analysis pipeline for a single file.

    Pipeline: pass1 → pass2 → quorum judge → retry if disagreement.

    Returns an AnalysisResult with the outcome.
    """
    language = detect_language(file_path, file_content)

    for attempt in range(max_retries + 1):
        try:
            # Pass 1
            pass1 = run_analysis_pass(client, file_path, file_content, language)

            # Pass 2
            pass2 = run_analysis_pass(client, file_path, file_content, language)

            # Quorum judge
            verdict = run_quorum_judge(client, file_path, pass1, pass2)

            if verdict.get("agree"):
                return AnalysisResult(
                    file_path=file_path,
                    status="complete",
                    pass1_result=pass1,
                    pass2_result=pass2,
                    quorum_result=verdict,
                    merged_result=verdict.get("merged_result", pass1),
                    retry_count=attempt,
                )
            else:
                log.info(
                    "Quorum disagreement on %s (attempt %d/%d): %s",
                    file_path, attempt + 1, max_retries + 1,
                    verdict.get("disagreements", []),
                )

        except AnalysisError as e:
            log.warning("Analysis error on %s (attempt %d/%d): %s",
                        file_path, attempt + 1, max_retries + 1, e)
            return AnalysisResult(
                file_path=file_path,
                status="flagged_for_opus",
                error=str(e),
                raw_output=e.raw_output,
                retry_count=attempt,
            )

    # Exhausted retries — flag for frontier model
    return AnalysisResult(
        file_path=file_path,
        status="flagged_for_opus",
        pass1_result=pass1,  # type: ignore[possibly-undefined]
        pass2_result=pass2,  # type: ignore[possibly-undefined]
        quorum_result=verdict,  # type: ignore[possibly-undefined]
        error=f"Quorum disagreement after {max_retries + 1} attempts",
        retry_count=max_retries,
    )


# -- Data types --

class AnalysisError(Exception):
    """Error during file analysis."""

    def __init__(self, message: str, file_path: str = "", raw_output: str = ""):
        super().__init__(message)
        self.file_path = file_path
        self.raw_output = raw_output


class AnalysisResult:
    """Result of analyzing a single file through the pipeline."""

    def __init__(
        self,
        file_path: str,
        status: str,
        pass1_result: Optional[dict] = None,
        pass2_result: Optional[dict] = None,
        quorum_result: Optional[dict] = None,
        merged_result: Optional[dict] = None,
        error: Optional[str] = None,
        raw_output: Optional[str] = None,
        retry_count: int = 0,
    ):
        self.file_path = file_path
        self.status = status
        self.pass1_result = pass1_result
        self.pass2_result = pass2_result
        self.quorum_result = quorum_result
        self.merged_result = merged_result
        self.error = error
        self.raw_output = raw_output
        self.retry_count = retry_count

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_flagged(self) -> bool:
        return self.status == "flagged_for_opus"
