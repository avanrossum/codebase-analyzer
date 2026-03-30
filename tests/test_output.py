"""Tests for output generation."""

import json
from pathlib import Path

import pytest

from codebase_analyzer.output import (
    ensure_output_dirs,
    generate_run_report,
    write_file_markdown,
    write_flagged_file,
)
from codebase_analyzer.state import StateDB


SAMPLE_ANALYSIS = {
    "purpose": "A utility module for string manipulation.",
    "type": "util",
    "language": "Python",
    "imports": ["re", "os"],
    "exports": ["slugify", "truncate"],
    "key_classes": [
        {
            "name": "TextProcessor",
            "purpose": "processes raw text input",
            "methods": ["clean", "normalize", "tokenize"],
        },
    ],
    "key_functions": [
        {"name": "slugify", "purpose": "converts text to URL-safe slug"},
        {"name": "truncate", "purpose": "truncates string with ellipsis"},
    ],
    "dependencies": {
        "imports_from": ["lib.core", "lib.config"],
        "imported_by_hint": "likely used by web handlers",
    },
    "language_specific_notes": "Uses Python 3.10+ match statement",
    "side_effects": "None",
    "complexity_notes": "Regex patterns are complex but well-documented",
}


@pytest.fixture
def output_dir(tmp_path):
    ensure_output_dirs(tmp_path)
    return tmp_path


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "state.db"
    with StateDB(db_path) as state:
        yield state


class TestEnsureOutputDirs:
    def test_creates_all_dirs(self, tmp_path):
        ensure_output_dirs(tmp_path)
        assert (tmp_path / "files").is_dir()
        assert (tmp_path / "flagged").is_dir()
        assert (tmp_path / "relationships").is_dir()

    def test_idempotent(self, tmp_path):
        ensure_output_dirs(tmp_path)
        ensure_output_dirs(tmp_path)
        assert (tmp_path / "files").is_dir()


class TestWriteFileMarkdown:
    def test_writes_file(self, output_dir):
        path = write_file_markdown(output_dir, "src/utils.py", SAMPLE_ANALYSIS)
        assert path.exists()
        assert path == output_dir / "files" / "src" / "utils.py.md"

    def test_contains_header(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "# utils.py" in content
        assert "**Type:** util" in content
        assert "**Language:** Python" in content

    def test_contains_purpose(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Purpose" in content
        assert "string manipulation" in content

    def test_contains_classes(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Key Classes" in content
        assert "**TextProcessor**" in content
        assert "clean, normalize, tokenize" in content

    def test_contains_functions(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Key Functions" in content
        assert "**slugify**" in content

    def test_contains_dependencies(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Dependencies" in content
        assert "lib.core" in content
        assert "web handlers" in content

    def test_omits_none_side_effects(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Side Effects" not in content

    def test_includes_real_side_effects(self, output_dir):
        analysis = {**SAMPLE_ANALYSIS, "side_effects": "Registers signal handler on import"}
        write_file_markdown(output_dir, "utils.py", analysis)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Side Effects" in content
        assert "signal handler" in content

    def test_includes_complexity_notes(self, output_dir):
        write_file_markdown(output_dir, "utils.py", SAMPLE_ANALYSIS)
        content = (output_dir / "files" / "utils.py.md").read_text()
        assert "## Complexity Notes" in content
        assert "Regex" in content

    def test_omits_empty_sections(self, output_dir):
        minimal = {"purpose": "does stuff", "type": "module", "language": "Python"}
        write_file_markdown(output_dir, "simple.py", minimal)
        content = (output_dir / "files" / "simple.py.md").read_text()
        assert "## Key Classes" not in content
        assert "## Key Functions" not in content
        assert "## Dependencies" not in content

    def test_nested_path(self, output_dir):
        path = write_file_markdown(output_dir, "src/lib/deep/module.py", SAMPLE_ANALYSIS)
        assert path.exists()
        assert "src/lib/deep" in str(path.parent)


class TestWriteFlaggedFile:
    def test_writes_json(self, output_dir):
        job = {
            "file_path": "tricky.py",
            "status": "flagged_for_opus",
            "retry_count": 3,
            "pass1_result": json.dumps({"purpose": "A"}),
            "pass2_result": json.dumps({"purpose": "B"}),
            "quorum_result": json.dumps({"agree": False, "disagreements": ["purpose"]}),
            "error_log": "Failed 3 times",
        }
        path = write_flagged_file(output_dir, job)
        assert path.exists()
        assert path == output_dir / "flagged" / "tricky.py.json"

        data = json.loads(path.read_text())
        assert data["file_path"] == "tricky.py"
        assert data["retry_count"] == 3
        assert data["pass1_result"]["purpose"] == "A"

    def test_handles_none_fields(self, output_dir):
        job = {
            "file_path": "broken.py",
            "status": "flagged_for_opus",
            "retry_count": 0,
            "pass1_result": None,
            "pass2_result": None,
            "quorum_result": None,
            "error_log": "JSON parse failure",
        }
        path = write_flagged_file(output_dir, job)
        data = json.loads(path.read_text())
        assert data["pass1_result"] is None

    def test_nested_path(self, output_dir):
        job = {
            "file_path": "src/lib/module.py",
            "status": "flagged_for_opus",
            "retry_count": 3,
        }
        path = write_flagged_file(output_dir, job)
        assert path.exists()
        assert "src/lib" in str(path.parent)


class TestRunReport:
    def test_generates_report(self, output_dir, db):
        db.set_metadata("repo_path", "/home/user/project")
        db.set_metadata("model", "qwen3:32b")
        db.add_jobs(["a.py", "b.py", "c.py"])
        db.update_status("a.py", "complete", final_description="done", retry_count=0)
        db.update_status("b.py", "complete", final_description="done", retry_count=1)
        db.update_status("c.py", "flagged_for_opus",
                         quorum_result={"agree": False, "disagreements": ["purpose"]},
                         error_log="Failed quorum")

        path = generate_run_report(
            output_dir, db,
            skipped_count=5,
            started_at="2026-03-30T10:00:00+00:00",
            completed_at="2026-03-30T12:30:00+00:00",
        )
        assert path.exists()
        content = path.read_text()

        assert "# Codebase Analysis Run Report" in content
        assert "/home/user/project" in content
        assert "qwen3:32b" in content
        assert "2h 30m" in content
        assert "Completed (quorum pass): 2" in content
        assert "Flagged for Opus: 1" in content
        assert "Skipped (too large / binary): 5" in content
        assert "First-pass agreement: 1" in content
        assert "Required 1 retry: 1" in content

    def test_report_with_flagged_table(self, output_dir, db):
        db.add_jobs(["problem.py"])
        db.update_status("problem.py", "flagged_for_opus",
                         quorum_result={"agree": False, "disagreements": ["type differs", "purpose unclear"]})

        path = generate_run_report(output_dir, db)
        content = path.read_text()
        assert "## Flagged Files" in content
        assert "problem.py" in content
        assert "type differs" in content

    def test_report_no_flagged(self, output_dir, db):
        db.add_jobs(["a.py"])
        db.update_status("a.py", "complete", final_description="done")

        path = generate_run_report(output_dir, db)
        content = path.read_text()
        assert "## Flagged Files" not in content

    def test_empty_db(self, output_dir, db):
        path = generate_run_report(output_dir, db)
        assert path.exists()
        content = path.read_text()
        assert "Total files: 0" in content
