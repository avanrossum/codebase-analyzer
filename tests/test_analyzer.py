"""Tests for the analyzer engine."""

import json
from unittest.mock import MagicMock, patch

import pytest

from codebase_analyzer.analyzer import (
    AnalysisError,
    AnalysisResult,
    OllamaClient,
    analyze_file,
    build_analysis_prompt,
    build_quorum_prompt,
    detect_language,
    extract_json,
    load_prompt_snippet,
    run_analysis_pass,
    run_quorum_judge,
)


# -- Language detection --

class TestDetectLanguage:
    def test_python_by_extension(self):
        assert detect_language("src/main.py") == "Python"

    def test_javascript_by_extension(self):
        assert detect_language("app.js") == "JavaScript"

    def test_typescript_by_extension(self):
        assert detect_language("types.ts") == "TypeScript"

    def test_tsx_by_extension(self):
        assert detect_language("App.tsx") == "TypeScript"

    def test_go_by_extension(self):
        assert detect_language("main.go") == "Go"

    def test_rust_by_extension(self):
        assert detect_language("lib.rs") == "Rust"

    def test_yaml_by_extension(self):
        assert detect_language("config.yaml") == "YAML"

    def test_shell_by_extension(self):
        assert detect_language("deploy.sh") == "Shell"

    def test_dockerfile_by_name(self):
        assert detect_language("Dockerfile", "") == "Dockerfile"

    def test_makefile_by_name(self):
        assert detect_language("Makefile", "") == "Shell"

    def test_gemfile_by_name(self):
        assert detect_language("Gemfile", "") == "Ruby"

    def test_shebang_python(self):
        assert detect_language("script", "#!/usr/bin/env python3\nprint()") == "Python"

    def test_shebang_bash(self):
        assert detect_language("run", "#!/bin/bash\necho hi") == "Shell"

    def test_shebang_node(self):
        assert detect_language("cli", "#!/usr/bin/env node\nconsole.log()") == "JavaScript"

    def test_unknown_extension(self):
        assert detect_language("file.xyz") == "Unknown"

    def test_no_extension_no_shebang(self):
        assert detect_language("README", "just text") == "Unknown"


class TestLoadPromptSnippet:
    def test_loads_python_snippet(self):
        snippet = load_prompt_snippet("Python")
        assert "Python" in snippet or "python" in snippet.lower()

    def test_loads_javascript_snippet(self):
        snippet = load_prompt_snippet("JavaScript")
        assert "module" in snippet.lower() or "import" in snippet.lower()

    def test_typescript_uses_javascript_snippet(self):
        js = load_prompt_snippet("JavaScript")
        ts = load_prompt_snippet("TypeScript")
        assert js == ts

    def test_unknown_language_returns_empty(self):
        assert load_prompt_snippet("Brainfuck") == ""


# -- JSON extraction --

class TestExtractJson:
    def test_plain_json(self):
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_fence(self):
        text = '```json\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_bare_fence(self):
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_json_with_preamble(self):
        text = 'Here is the analysis:\n\n{"purpose": "test module"}'
        result = extract_json(text)
        assert result["purpose"] == "test module"

    def test_json_with_trailing_text(self):
        text = '{"key": "value"}\n\nSome trailing explanation.'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_nested_json(self):
        obj = {
            "purpose": "test",
            "dependencies": {"imports_from": ["os", "sys"]},
            "key_classes": [{"name": "Foo", "methods": ["bar"]}],
        }
        result = extract_json(json.dumps(obj))
        assert result == obj

    def test_json_with_escaped_quotes(self):
        text = '{"purpose": "handles \\"special\\" chars"}'
        result = extract_json(text)
        assert "special" in result["purpose"]

    def test_no_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json("no json here at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json("")


# -- Prompt building --

class TestBuildPrompts:
    def test_analysis_prompt_includes_language(self):
        system, user = build_analysis_prompt("test.py", "print('hi')", "Python")
        assert "Python" in system
        assert "test.py" in user
        assert "print('hi')" in user

    def test_analysis_prompt_includes_snippet(self):
        system, _ = build_analysis_prompt("test.py", "pass", "Python")
        # Should have the Python-specific context injected
        assert "Python" in system

    def test_quorum_prompt_includes_both_analyses(self):
        p1 = {"purpose": "auth module"}
        p2 = {"purpose": "authentication handler"}
        system, user = build_quorum_prompt("auth.py", p1, p2)
        assert "auth module" in user
        assert "authentication handler" in user
        assert "auth.py" in user
        assert "agree" in system


# -- Mock Ollama client for pipeline tests --

def make_mock_client(responses: list[str]) -> OllamaClient:
    """Create a mock OllamaClient that returns predefined responses."""
    client = OllamaClient.__new__(OllamaClient)
    client.base_url = "http://mock"
    client.model = "mock"
    client._responses = iter(responses)
    client.chat = MagicMock(side_effect=lambda s, u: next(client._responses))
    return client


SAMPLE_ANALYSIS = {
    "purpose": "A utility module for string manipulation",
    "type": "util",
    "language": "Python",
    "imports": ["re", "os"],
    "exports": ["slugify", "truncate"],
    "key_classes": [],
    "key_functions": [
        {"name": "slugify", "purpose": "converts text to URL-safe slug"},
        {"name": "truncate", "purpose": "truncates string with ellipsis"},
    ],
    "dependencies": {
        "imports_from": [],
        "imported_by_hint": "likely used by web handlers",
    },
    "language_specific_notes": "Uses Python 3.10+ match statement",
    "side_effects": "None",
    "complexity_notes": "None",
}


class TestRunAnalysisPass:
    def test_successful_pass(self):
        client = make_mock_client([json.dumps(SAMPLE_ANALYSIS)])
        result = run_analysis_pass(client, "utils.py", "def slugify(): pass", "Python")
        assert result["purpose"] == SAMPLE_ANALYSIS["purpose"]

    def test_retries_on_bad_json(self):
        client = make_mock_client([
            "This is not JSON",
            "Still not JSON",
            json.dumps(SAMPLE_ANALYSIS),
        ])
        result = run_analysis_pass(client, "utils.py", "code", "Python")
        assert result["purpose"] == SAMPLE_ANALYSIS["purpose"]
        assert client.chat.call_count == 3

    def test_raises_after_max_json_retries(self):
        client = make_mock_client([
            "bad1", "bad2", "bad3",
        ])
        with pytest.raises(AnalysisError, match="JSON parse failure"):
            run_analysis_pass(client, "utils.py", "code", "Python")


class TestRunQuorumJudge:
    def test_agree_verdict(self):
        verdict = {
            "agree": True,
            "merged_result": SAMPLE_ANALYSIS,
            "disagreements": [],
            "confidence": "high",
        }
        client = make_mock_client([json.dumps(verdict)])
        result = run_quorum_judge(client, "utils.py", SAMPLE_ANALYSIS, SAMPLE_ANALYSIS)
        assert result["agree"] is True
        assert result["confidence"] == "high"

    def test_disagree_verdict(self):
        verdict = {
            "agree": False,
            "disagreements": ["purpose differs"],
            "confidence": "low",
        }
        client = make_mock_client([json.dumps(verdict)])
        result = run_quorum_judge(client, "utils.py", {"purpose": "A"}, {"purpose": "B"})
        assert result["agree"] is False

    def test_missing_agree_field_retries(self):
        client = make_mock_client([
            '{"confidence": "high"}',  # missing "agree"
            '{"confidence": "high"}',
            json.dumps({"agree": True, "merged_result": {}, "confidence": "high"}),
        ])
        result = run_quorum_judge(client, "utils.py", {}, {})
        assert result["agree"] is True
        assert client.chat.call_count == 3


class TestAnalyzeFile:
    def test_happy_path(self):
        verdict = {
            "agree": True,
            "merged_result": SAMPLE_ANALYSIS,
            "disagreements": [],
            "confidence": "high",
        }
        client = make_mock_client([
            json.dumps(SAMPLE_ANALYSIS),  # pass 1
            json.dumps(SAMPLE_ANALYSIS),  # pass 2
            json.dumps(verdict),          # judge
        ])
        result = analyze_file(client, "utils.py", "def slugify(): pass")
        assert result.is_complete
        assert result.merged_result == SAMPLE_ANALYSIS
        assert result.retry_count == 0

    def test_retry_on_disagreement(self):
        disagree = json.dumps({
            "agree": False,
            "disagreements": ["type differs"],
            "confidence": "low",
        })
        agree = json.dumps({
            "agree": True,
            "merged_result": SAMPLE_ANALYSIS,
            "confidence": "high",
        })
        client = make_mock_client([
            json.dumps(SAMPLE_ANALYSIS), json.dumps(SAMPLE_ANALYSIS), disagree,   # attempt 1
            json.dumps(SAMPLE_ANALYSIS), json.dumps(SAMPLE_ANALYSIS), agree,      # attempt 2
        ])
        result = analyze_file(client, "utils.py", "code", max_retries=3)
        assert result.is_complete
        assert result.retry_count == 1

    def test_flagged_after_max_retries(self):
        disagree = json.dumps({
            "agree": False,
            "disagreements": ["purpose"],
            "confidence": "low",
        })
        responses = []
        for _ in range(4):  # 1 initial + 3 retries
            responses.extend([
                json.dumps(SAMPLE_ANALYSIS),
                json.dumps(SAMPLE_ANALYSIS),
                disagree,
            ])
        client = make_mock_client(responses)
        result = analyze_file(client, "tricky.py", "code", max_retries=3)
        assert result.is_flagged
        assert result.retry_count == 3
        assert "disagreement" in result.error.lower()

    def test_flagged_on_analysis_error(self):
        client = make_mock_client(["bad json"] * 3)
        result = analyze_file(client, "broken.py", "code")
        assert result.is_flagged
        assert result.error is not None


class TestAnalysisResult:
    def test_complete_result(self):
        r = AnalysisResult("a.py", "complete", merged_result={"purpose": "test"})
        assert r.is_complete
        assert not r.is_flagged

    def test_flagged_result(self):
        r = AnalysisResult("a.py", "flagged_for_opus", error="failed")
        assert r.is_flagged
        assert not r.is_complete
