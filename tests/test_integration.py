"""Integration tests for the full CLI pipeline with mocked Ollama."""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from codebase_analyzer.cli import cli


SAMPLE_ANALYSIS = json.dumps({
    "purpose": "A test module",
    "type": "module",
    "language": "Python",
    "imports": ["os"],
    "exports": ["main"],
    "key_classes": [],
    "key_functions": [{"name": "main", "purpose": "entry point"}],
    "dependencies": {"imports_from": [], "imported_by_hint": ""},
    "language_specific_notes": "None",
    "side_effects": "None",
    "complexity_notes": "None",
})

QUORUM_AGREE = json.dumps({
    "agree": True,
    "merged_result": json.loads(SAMPLE_ANALYSIS),
    "disagreements": [],
    "confidence": "high",
})


def _make_repo(tmp_path):
    """Create a minimal test repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main(): pass")
    (repo / "utils.py").write_text("def helper(): pass")
    (repo / "setup.py").write_text("from setuptools import setup")
    return repo


def _mock_chat(system, user):
    """Mock Ollama chat that returns appropriate responses."""
    if "comparing two independent analyses" in system:
        return QUORUM_AGREE
    return SAMPLE_ANALYSIS


class TestAnalyzeCommand:
    def test_full_pipeline(self, tmp_path):
        repo = _make_repo(tmp_path)
        output = tmp_path / "output"

        with patch("codebase_analyzer.cli.LLMClient") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.chat.side_effect = _mock_chat

            runner = CliRunner()
            result = runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])

        assert result.exit_code == 0, result.output
        assert "Starting" in result.output
        assert "✓" in result.output

        # Check output files exist
        assert (output / "files" / "main.py.md").exists()
        assert (output / "files" / "utils.py.md").exists()
        assert (output / "files" / "setup.py.md").exists()
        assert (output / "run_report.md").exists()
        assert (output / "analyzer_state.db").exists()

        # Check markdown content
        md = (output / "files" / "main.py.md").read_text()
        assert "# main.py" in md
        assert "A test module" in md

        # Check run report
        report = (output / "run_report.md").read_text()
        assert "Completed (quorum pass): 3" in report

    def test_resume(self, tmp_path):
        repo = _make_repo(tmp_path)
        output = tmp_path / "output"

        with patch("codebase_analyzer.cli.LLMClient") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.chat.side_effect = _mock_chat

            runner = CliRunner()

            # First run
            result = runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])
            assert result.exit_code == 0

            # Second run (resume — all done)
            result = runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])
            assert result.exit_code == 0
            assert "Resuming" in result.output
            assert "already processed" in result.output

    def test_resume_with_new_file(self, tmp_path):
        repo = _make_repo(tmp_path)
        output = tmp_path / "output"

        with patch("codebase_analyzer.cli.LLMClient") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.chat.side_effect = _mock_chat

            runner = CliRunner()

            # First run
            runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])

            # Add a new file
            (repo / "new_module.py").write_text("def new(): pass")

            # Resume
            result = runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])
            assert result.exit_code == 0
            assert "1 new files" in result.output
            assert (output / "files" / "new_module.py.md").exists()

    def test_handles_flagged_files(self, tmp_path):
        repo = _make_repo(tmp_path)
        output = tmp_path / "output"

        disagree = json.dumps({
            "agree": False,
            "disagreements": ["purpose differs"],
            "confidence": "low",
        })

        call_count = 0

        def mock_always_disagree(system, user):
            nonlocal call_count
            call_count += 1
            if "comparing two independent analyses" in system:
                return disagree
            return SAMPLE_ANALYSIS

        with patch("codebase_analyzer.cli.LLMClient") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.chat.side_effect = mock_always_disagree

            runner = CliRunner()
            result = runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
                "--max-retries", "1",
            ])

        assert result.exit_code == 0
        assert "flagged" in result.output

        # Should have flagged JSON files
        flagged_dir = output / "flagged"
        flagged_files = list(flagged_dir.rglob("*.json"))
        assert len(flagged_files) > 0


class TestStatusCommand:
    def test_shows_status(self, tmp_path):
        repo = _make_repo(tmp_path)
        output = tmp_path / "output"

        with patch("codebase_analyzer.cli.LLMClient") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.chat.side_effect = _mock_chat

            runner = CliRunner()
            runner.invoke(cli, [
                "analyze", str(repo),
                "--output", str(output),
                "--profiles", "python",
            ])

        result = runner.invoke(cli, ["status", str(output)])
        assert result.exit_code == 0
        assert "Completed" in result.output

    def test_no_state_file(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(empty)])
        assert result.exit_code == 1
