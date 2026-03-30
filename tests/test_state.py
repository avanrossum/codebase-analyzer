"""Tests for the SQLite state layer."""

import json
from pathlib import Path

import pytest

from codebase_analyzer.state import StateDB, ALL_STATUSES


@pytest.fixture
def db(tmp_path):
    """Create a fresh StateDB in a temp directory."""
    db_path = tmp_path / "test_state.db"
    with StateDB(db_path) as state:
        yield state


class TestInitialization:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "new.db"
        assert not db_path.exists()
        state = StateDB(db_path)
        assert db_path.exists()
        state.close()

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "sub" / "dir" / "state.db"
        state = StateDB(db_path)
        assert db_path.exists()
        state.close()

    def test_exists_returns_true_after_init(self, db):
        assert db.exists()

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        with StateDB(db_path) as state:
            state.add_jobs(["test.py"])
            job = state.get_job("test.py")
            assert job is not None


class TestJobOperations:
    def test_add_jobs(self, db):
        db.add_jobs(["a.py", "b.py", "c.py"])
        assert len(db.get_jobs_by_status("pending")) == 3

    def test_add_jobs_skips_duplicates(self, db):
        db.add_jobs(["a.py", "b.py"])
        db.add_jobs(["b.py", "c.py"])
        all_pending = db.get_jobs_by_status("pending")
        assert len(all_pending) == 3

    def test_add_jobs_sets_timestamps(self, db):
        db.add_jobs(["a.py"])
        job = db.get_job("a.py")
        assert job["created_at"] is not None
        assert job["updated_at"] is not None

    def test_add_jobs_default_status(self, db):
        db.add_jobs(["a.py"])
        job = db.get_job("a.py")
        assert job["status"] == "pending"
        assert job["retry_count"] == 0

    def test_get_job_returns_none_for_missing(self, db):
        assert db.get_job("nonexistent.py") is None

    def test_add_empty_list(self, db):
        db.add_jobs([])
        assert db.get_progress() == {}


class TestStatusUpdates:
    def test_update_status(self, db):
        db.add_jobs(["a.py"])
        db.update_status("a.py", "pass1_done")
        job = db.get_job("a.py")
        assert job["status"] == "pass1_done"

    def test_update_status_with_result(self, db):
        db.add_jobs(["a.py"])
        result = {"purpose": "test file", "type": "module"}
        db.update_status("a.py", "pass1_done", pass1_result=result)
        job = db.get_job("a.py")
        assert json.loads(job["pass1_result"]) == result

    def test_update_status_with_string_result(self, db):
        db.add_jobs(["a.py"])
        result_str = '{"purpose": "test"}'
        db.update_status("a.py", "pass1_done", pass1_result=result_str)
        job = db.get_job("a.py")
        assert job["pass1_result"] == result_str

    def test_update_status_updates_timestamp(self, db):
        db.add_jobs(["a.py"])
        original = db.get_job("a.py")["updated_at"]
        db.update_status("a.py", "pass1_done")
        updated = db.get_job("a.py")["updated_at"]
        assert updated >= original

    def test_update_retry_count(self, db):
        db.add_jobs(["a.py"])
        db.update_status("a.py", "retry_1", retry_count=1)
        job = db.get_job("a.py")
        assert job["retry_count"] == 1

    def test_update_error_log(self, db):
        db.add_jobs(["a.py"])
        db.update_status("a.py", "error", error_log="Connection refused")
        job = db.get_job("a.py")
        assert job["error_log"] == "Connection refused"

    def test_update_final_description(self, db):
        db.add_jobs(["a.py"])
        md = "# a.py\n\nA test module."
        db.update_status("a.py", "complete", final_description=md)
        job = db.get_job("a.py")
        assert job["final_description"] == md

    def test_invalid_status_raises(self, db):
        db.add_jobs(["a.py"])
        with pytest.raises(ValueError, match="Invalid status"):
            db.update_status("a.py", "bogus_status")

    def test_unknown_field_raises(self, db):
        db.add_jobs(["a.py"])
        with pytest.raises(ValueError, match="Unknown field"):
            db.update_status("a.py", "pending", nonexistent_field="x")


class TestQueries:
    def test_get_jobs_by_status(self, db):
        db.add_jobs(["a.py", "b.py", "c.py"])
        db.update_status("a.py", "pass1_done")
        db.update_status("b.py", "complete", final_description="done")

        pending = db.get_jobs_by_status("pending")
        assert len(pending) == 1
        assert pending[0]["file_path"] == "c.py"

        done = db.get_jobs_by_status("complete")
        assert len(done) == 1

    def test_get_jobs_by_multiple_statuses(self, db):
        db.add_jobs(["a.py", "b.py", "c.py"])
        db.update_status("a.py", "pass1_done")
        db.update_status("b.py", "pass2_done")

        results = db.get_jobs_by_status("pass1_done", "pass2_done")
        assert len(results) == 2

    def test_get_resumable_jobs(self, db):
        db.add_jobs(["a.py", "b.py", "c.py", "d.py"])
        db.update_status("a.py", "pass1_done")
        db.update_status("b.py", "complete", final_description="done")
        db.update_status("d.py", "flagged_for_opus")

        resumable = db.get_resumable_jobs()
        paths = [j["file_path"] for j in resumable]
        assert "a.py" in paths
        assert "c.py" in paths
        assert "b.py" not in paths
        assert "d.py" not in paths

    def test_resumable_jobs_ordered_by_pipeline_stage(self, db):
        db.add_jobs(["early.py", "late.py", "mid.py"])
        db.update_status("late.py", "quorum_fail")
        db.update_status("mid.py", "pass1_done")
        # early.py stays pending

        resumable = db.get_resumable_jobs()
        statuses = [j["status"] for j in resumable]
        assert statuses == ["pending", "pass1_done", "quorum_fail"]

    def test_get_all_tracked_paths(self, db):
        db.add_jobs(["a.py", "b.py", "c.py"])
        db.update_status("c.py", "removed")

        tracked = db.get_all_tracked_paths()
        assert tracked == {"a.py", "b.py"}


class TestMarkRemoved:
    def test_mark_removed(self, db):
        db.add_jobs(["a.py", "b.py", "c.py"])
        db.mark_removed(["b.py", "c.py"])

        assert db.get_job("b.py")["status"] == "removed"
        assert db.get_job("c.py")["status"] == "removed"
        assert db.get_job("a.py")["status"] == "pending"

    def test_mark_removed_empty_list(self, db):
        db.add_jobs(["a.py"])
        db.mark_removed([])
        assert db.get_job("a.py")["status"] == "pending"


class TestProgress:
    def test_get_progress(self, db):
        db.add_jobs(["a.py", "b.py", "c.py", "d.py"])
        db.update_status("a.py", "complete", final_description="done")
        db.update_status("b.py", "pass1_done")
        db.update_status("c.py", "flagged_for_opus")

        progress = db.get_progress()
        assert progress["complete"] == 1
        assert progress["pass1_done"] == 1
        assert progress["flagged_for_opus"] == 1
        assert progress["pending"] == 1

    def test_get_total_counts(self, db):
        db.add_jobs(["a.py", "b.py", "c.py", "d.py", "e.py"])
        db.update_status("a.py", "complete", final_description="done")
        db.update_status("b.py", "complete", final_description="done")
        db.update_status("c.py", "flagged_for_opus")
        db.update_status("d.py", "error", error_log="fail")

        counts = db.get_total_counts()
        assert counts["total"] == 5
        assert counts["completed"] == 2
        assert counts["flagged"] == 1
        assert counts["errors"] == 1
        assert counts["in_progress"] == 1

    def test_empty_progress(self, db):
        progress = db.get_progress()
        assert progress == {}
        counts = db.get_total_counts()
        assert counts["total"] == 0


class TestMetadata:
    def test_set_and_get_metadata(self, db):
        db.set_metadata("repo_path", "/home/user/project")
        assert db.get_metadata("repo_path") == "/home/user/project"

    def test_get_missing_metadata(self, db):
        assert db.get_metadata("nonexistent") is None

    def test_update_metadata(self, db):
        db.set_metadata("model", "qwen3:32b")
        db.set_metadata("model", "llama3:70b")
        assert db.get_metadata("model") == "llama3:70b"

    def test_get_all_metadata(self, db):
        db.set_metadata("repo_path", "/project")
        db.set_metadata("model", "qwen3:32b")
        db.set_metadata("started_at", "2026-03-30T12:00:00Z")

        meta = db.get_all_metadata()
        assert meta == {
            "repo_path": "/project",
            "model": "qwen3:32b",
            "started_at": "2026-03-30T12:00:00Z",
        }


class TestFullPipeline:
    """Simulate a file going through the complete analysis pipeline."""

    def test_happy_path(self, db):
        db.add_jobs(["module.py"])

        # Pass 1
        p1 = {"purpose": "handles auth", "type": "module"}
        db.update_status("module.py", "pass1_done", pass1_result=p1)

        # Pass 2
        p2 = {"purpose": "authentication module", "type": "module"}
        db.update_status("module.py", "pass2_done", pass2_result=p2)

        # Quorum passes
        merged = {"purpose": "authentication module", "type": "module"}
        db.update_status("module.py", "quorum_pass", quorum_result={
            "agree": True, "merged_result": merged, "confidence": "high",
        })

        # Write final output
        md = "# module.py\n\n**Type:** module\n\n## Purpose\n\nAuthentication module."
        db.update_status("module.py", "complete", final_description=md)

        job = db.get_job("module.py")
        assert job["status"] == "complete"
        assert job["final_description"] == md
        assert job["retry_count"] == 0

    def test_retry_then_flag(self, db):
        db.add_jobs(["tricky.py"])

        for attempt in range(1, 4):
            db.update_status("tricky.py", "pass1_done", pass1_result={"v": attempt})
            db.update_status("tricky.py", "pass2_done", pass2_result={"v": attempt})
            db.update_status(
                "tricky.py",
                f"retry_{attempt}" if attempt < 4 else "quorum_fail",
                quorum_result={"agree": False},
                retry_count=attempt,
            )

        # After 3 retries, flag for opus
        db.update_status("tricky.py", "flagged_for_opus",
                         error_log="Failed quorum 3 times: purpose disagreement")

        job = db.get_job("tricky.py")
        assert job["status"] == "flagged_for_opus"
        assert job["retry_count"] == 3
