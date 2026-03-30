"""Markdown generation for analysis results."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from codebase_analyzer.state import StateDB


def ensure_output_dirs(output_dir: Path):
    """Create the output directory structure."""
    (output_dir / "files").mkdir(parents=True, exist_ok=True)
    (output_dir / "flagged").mkdir(parents=True, exist_ok=True)
    (output_dir / "relationships").mkdir(parents=True, exist_ok=True)


def write_file_markdown(output_dir: Path, file_path: str, analysis: dict) -> Path:
    """Write a per-file markdown description from merged analysis results.

    Returns the path to the written file.
    """
    md_path = output_dir / "files" / f"{file_path}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# {file_path}", ""]

    # Type and language header
    file_type = analysis.get("type", "unknown")
    language = analysis.get("language", "Unknown")
    lines.append(f"**Type:** {file_type} | **Language:** {language}")
    lines.append("")

    # Purpose
    purpose = analysis.get("purpose", "")
    if purpose:
        lines.extend(["## Purpose", "", purpose, ""])

    # Key Classes
    classes = analysis.get("key_classes", [])
    if classes:
        lines.extend(["## Key Classes", ""])
        for cls in classes:
            name = cls.get("name", "")
            cls_purpose = cls.get("purpose", "")
            methods = cls.get("methods", [])
            lines.append(f"- **{name}**: {cls_purpose}")
            if methods:
                lines.append(f"  - Methods: {', '.join(methods)}")
        lines.append("")

    # Key Functions
    functions = analysis.get("key_functions", [])
    if functions:
        lines.extend(["## Key Functions", ""])
        for fn in functions:
            name = fn.get("name", "")
            fn_purpose = fn.get("purpose", "")
            lines.append(f"- **{name}**: {fn_purpose}")
        lines.append("")

    # Dependencies
    deps = analysis.get("dependencies", {})
    imports_from = deps.get("imports_from", [])
    imported_by = deps.get("imported_by_hint", "")
    if imports_from or imported_by:
        lines.extend(["## Dependencies", ""])
        if imports_from:
            lines.append(f"- **Imports from:** {', '.join(imports_from)}")
        if imported_by:
            lines.append(f"- **Imported by (hint):** {imported_by}")
        lines.append("")

    # Side Effects
    side_effects = analysis.get("side_effects", "")
    if side_effects and side_effects.lower() not in ("none", "n/a", ""):
        lines.extend(["## Side Effects", "", side_effects, ""])

    # Language-Specific Notes
    lang_notes = analysis.get("language_specific_notes", "")
    if lang_notes and lang_notes.lower() not in ("none", "n/a", ""):
        lines.extend(["## Language-Specific Notes", "", lang_notes, ""])

    # Complexity Notes
    complexity = analysis.get("complexity_notes", "")
    if complexity and complexity.lower() not in ("none", "n/a", ""):
        lines.extend(["## Complexity Notes", "", complexity, ""])

    md_path.write_text("\n".join(lines))
    return md_path


def write_flagged_file(output_dir: Path, job: dict) -> Path:
    """Write a flagged file's full analysis history as JSON.

    Returns the path to the written file.
    """
    file_path = job["file_path"]
    json_path = output_dir / "flagged" / f"{file_path}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)

    history = {
        "file_path": file_path,
        "status": job["status"],
        "retry_count": job["retry_count"],
        "pass1_result": _parse_json_field(job.get("pass1_result")),
        "pass2_result": _parse_json_field(job.get("pass2_result")),
        "quorum_result": _parse_json_field(job.get("quorum_result")),
        "error_log": job.get("error_log"),
    }

    json_path.write_text(json.dumps(history, indent=2))
    return json_path


def generate_run_report(
    output_dir: Path,
    db: StateDB,
    skipped_count: int = 0,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> Path:
    """Generate the run report markdown file.

    Returns the path to the written file.
    """
    repo_path = db.get_metadata("repo_path") or "unknown"
    model = db.get_metadata("model") or "unknown"
    started = started_at or db.get_metadata("started_at") or "unknown"
    completed = completed_at or datetime.now(timezone.utc).isoformat()

    # Calculate duration
    duration_str = _format_duration(started, completed)

    # Progress stats
    progress = db.get_progress()
    total = sum(progress.values())
    completed_count = progress.get("complete", 0)
    flagged_count = progress.get("flagged_for_opus", 0)
    error_count = progress.get("error", 0)
    removed_count = progress.get("removed", 0)
    active = total - completed_count - flagged_count - error_count - removed_count

    # Quorum stats from retry counts
    retry_stats = _get_retry_stats(db)

    # Flagged files detail
    flagged_jobs = db.get_jobs_by_status("flagged_for_opus")

    lines = [
        "# Codebase Analysis Run Report",
        "",
        f"- **Repository:** {repo_path}",
        f"- **Model:** {model}",
        f"- **Started:** {started}",
        f"- **Completed:** {completed}",
        f"- **Duration:** {duration_str}",
        "",
        "## Progress",
        "",
        f"- Total files: {total:,}",
        f"- Completed (quorum pass): {completed_count:,}"
        + (f" ({completed_count/total*100:.1f}%)" if total else ""),
        f"- Flagged for Opus: {flagged_count:,}"
        + (f" ({flagged_count/total*100:.1f}%)" if total else ""),
        f"- Skipped (too large / binary): {skipped_count:,}",
        f"- Errors: {error_count:,}",
    ]

    if active > 0:
        lines.append(f"- Still in progress: {active:,}")

    # Quorum stats
    lines.extend([
        "",
        "## Quorum Stats",
        "",
        f"- First-pass agreement: {retry_stats.get(0, 0):,}",
        f"- Required 1 retry: {retry_stats.get(1, 0):,}",
        f"- Required 2 retries: {retry_stats.get(2, 0):,}",
        f"- Required 3 retries: {retry_stats.get(3, 0):,}",
        f"- Failed all retries: {flagged_count:,}",
    ])

    # Flagged files table
    if flagged_jobs:
        lines.extend([
            "",
            "## Flagged Files",
            "",
            "| File | Disagreement Summary |",
            "|------|---------------------|",
        ])
        for job in flagged_jobs:
            fp = job["file_path"]
            summary = _extract_disagreement_summary(job)
            lines.append(f"| {fp} | {summary} |")

    lines.append("")
    report_path = output_dir / "run_report.md"
    report_path.write_text("\n".join(lines))
    return report_path


def _parse_json_field(value: Optional[str]) -> Optional[dict]:
    """Parse a JSON string field, returning None if empty or invalid."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _format_duration(started: str, completed: str) -> str:
    """Format the duration between two ISO timestamps."""
    try:
        start_dt = datetime.fromisoformat(started)
        end_dt = datetime.fromisoformat(completed)
        delta = end_dt - start_dt
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"
    except (ValueError, TypeError):
        return "unknown"


def _get_retry_stats(db: StateDB) -> dict[int, int]:
    """Get counts of completed jobs by retry count."""
    completed = db.get_jobs_by_status("complete")
    stats: dict[int, int] = {}
    for job in completed:
        rc = job.get("retry_count", 0)
        stats[rc] = stats.get(rc, 0) + 1
    return stats


def _extract_disagreement_summary(job: dict) -> str:
    """Extract a brief disagreement summary from a flagged job."""
    quorum = _parse_json_field(job.get("quorum_result"))
    if quorum and quorum.get("disagreements"):
        return "; ".join(quorum["disagreements"][:3])

    error_log = job.get("error_log", "")
    if error_log:
        return error_log[:100]

    return "No details available"
