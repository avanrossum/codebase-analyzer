"""CLI entry point for codebase-analyzer."""

import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from codebase_analyzer import __version__
from codebase_analyzer.analyzer import OllamaClient, analyze_file
from codebase_analyzer.output import (
    ensure_output_dirs,
    generate_run_report,
    write_file_markdown,
    write_flagged_file,
)
from codebase_analyzer.state import StateDB
from codebase_analyzer.walker import walk_repo

console = Console()

# Graceful shutdown flag
_shutdown_requested = False


def _handle_sigint(signum, frame):
    global _shutdown_requested
    if _shutdown_requested:
        # Second Ctrl+C — force exit
        console.print("\n[red]Force quit.[/red]")
        sys.exit(1)
    _shutdown_requested = True
    console.print("\n[yellow]Shutting down after current file... (Ctrl+C again to force)[/yellow]")


@click.group()
@click.version_option(version=__version__, prog_name="codebase-analyzer")
def cli():
    """Analyze codebases and generate structured file documentation using local LLMs."""


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--output", "-o",
    required=True,
    type=click.Path(),
    help="Output directory for analysis results.",
)
@click.option(
    "--profiles",
    default=None,
    help="Comma-separated language profiles (e.g. python,web,config). Auto-detected if omitted.",
)
@click.option(
    "--profile-file",
    type=click.Path(exists=True),
    default=None,
    help="Path to a custom profile YAML file.",
)
@click.option(
    "--all-text-files",
    is_flag=True,
    default=False,
    help="Include all text files regardless of profile. Binary files still excluded.",
)
@click.option(
    "--model",
    default="qwen3:32b-q5_K_M",
    show_default=True,
    help="Ollama model to use for analysis.",
)
@click.option(
    "--ollama-url",
    default="http://localhost:11434",
    show_default=True,
    help="Ollama API base URL.",
)
@click.option(
    "--max-retries",
    default=3,
    show_default=True,
    help="Maximum quorum retry attempts before flagging for frontier model.",
)
@click.option(
    "--max-file-size",
    default=100_000,
    show_default=True,
    help="Maximum file size in bytes before chunking.",
)
@click.option(
    "--concurrency",
    default=1,
    show_default=True,
    help="Number of parallel Ollama requests (1 is safest for single-GPU).",
)
def analyze(repo_path, output, profiles, profile_file, all_text_files,
            model, ollama_url, max_retries, max_file_size, concurrency):
    """Analyze a codebase and generate file descriptions.

    REPO_PATH is the root directory of the repository to analyze.
    Automatically resumes from previous state if an existing analysis is found
    in the output directory.
    """
    global _shutdown_requested
    _shutdown_requested = False
    signal.signal(signal.SIGINT, _handle_sigint)

    repo_path = Path(repo_path).resolve()
    output_dir = Path(output).resolve()
    ensure_output_dirs(output_dir)

    db_path = output_dir / "analyzer_state.db"
    is_resume = db_path.exists()

    with StateDB(db_path) as db:
        started_at = datetime.now(timezone.utc).isoformat()

        if is_resume:
            console.print(f"[green]Resuming[/green] analysis from {output_dir}")
            db.set_metadata("last_resumed_at", started_at)
        else:
            console.print(f"[green]Starting[/green] analysis of {repo_path}")
            db.set_metadata("repo_path", str(repo_path))
            db.set_metadata("model", model)
            db.set_metadata("started_at", started_at)

        # Walk repo
        console.print("Scanning repository...")
        walk_result = walk_repo(
            repo_path,
            profiles=profiles,
            profile_file=Path(profile_file) if profile_file else None,
            all_text_files=all_text_files,
            max_file_size=max_file_size,
        )

        console.print(
            f"Found [bold]{len(walk_result.files):,}[/bold] files "
            f"using profiles: {', '.join(walk_result.profiles_used)}"
        )
        if walk_result.skipped:
            console.print(f"Skipped {len(walk_result.skipped):,} files (binary/empty/large)")

        # Sync with state DB
        if is_resume:
            existing = db.get_all_tracked_paths()
            new_files = [f for f in walk_result.files if f not in existing]
            removed = [f for f in existing if f not in set(walk_result.files)]

            if new_files:
                db.add_jobs(new_files)
                console.print(f"Added {len(new_files):,} new files")
            if removed:
                db.mark_removed(removed)
                console.print(f"Marked {len(removed):,} removed files")
        else:
            db.add_jobs(walk_result.files)

        # Get jobs to process
        jobs = db.get_resumable_jobs()
        total = len(jobs)
        if total == 0:
            console.print("[green]All files already processed.[/green]")
            _finalize(output_dir, db, walk_result, started_at)
            return

        console.print(f"Processing [bold]{total:,}[/bold] files...")
        console.print()

        # Analysis loop
        with OllamaClient(base_url=ollama_url, model=model) as client:
            for i, job in enumerate(jobs, 1):
                if _shutdown_requested:
                    console.print(f"\n[yellow]Stopped after {i - 1}/{total} files.[/yellow]")
                    break

                file_path = job["file_path"]
                abs_path = repo_path / file_path

                # Read file content
                try:
                    content = abs_path.read_text(errors="replace")
                except OSError as e:
                    console.print(f"[{i}/{total}] [red]error:[/red] {file_path}: {e}")
                    db.update_status(file_path, "error", error_log=str(e))
                    continue

                console.print(f"[{i}/{total}] analyzing: {file_path}")

                try:
                    result = analyze_file(client, file_path, content, max_retries=max_retries)
                except ConnectionError as e:
                    console.print(f"\n[red]Lost connection to Ollama:[/red] {e}")
                    console.print("State saved. Resume by running the same command.")
                    _finalize(output_dir, db, walk_result, started_at)
                    sys.exit(1)

                # Update state and write output
                if result.is_complete:
                    db.update_status(
                        file_path, "complete",
                        pass1_result=result.pass1_result,
                        pass2_result=result.pass2_result,
                        quorum_result=result.quorum_result,
                        final_description=json.dumps(result.merged_result),
                        retry_count=result.retry_count,
                    )
                    write_file_markdown(output_dir, file_path, result.merged_result)

                    confidence = ""
                    if result.quorum_result:
                        confidence = f" ({result.quorum_result.get('confidence', '')} confidence)"
                    retry_note = f" [retry {result.retry_count}]" if result.retry_count > 0 else ""
                    console.print(
                        f"[{i}/{total}] [green]✓[/green] {file_path}{confidence}{retry_note}"
                    )
                else:
                    db.update_status(
                        file_path, "flagged_for_opus",
                        pass1_result=result.pass1_result,
                        pass2_result=result.pass2_result,
                        quorum_result=result.quorum_result,
                        error_log=result.error,
                        retry_count=result.retry_count,
                    )
                    flagged_job = db.get_job(file_path)
                    write_flagged_file(output_dir, flagged_job)

                    console.print(
                        f"[{i}/{total}] [red]✗ flagged:[/red] {file_path} — {result.error}"
                    )

        _finalize(output_dir, db, walk_result, started_at)

    console.print("\n[green]Done.[/green]")


def _finalize(output_dir, db, walk_result, started_at):
    """Generate the run report."""
    completed_at = datetime.now(timezone.utc).isoformat()
    generate_run_report(
        output_dir, db,
        skipped_count=len(walk_result.skipped),
        started_at=started_at,
        completed_at=completed_at,
    )


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False))
def status(output_dir):
    """Check progress of an analysis run.

    OUTPUT_DIR is the directory containing analysis results and state.
    """
    output_dir = Path(output_dir)
    db_path = output_dir / "analyzer_state.db"

    if not db_path.exists():
        console.print("[red]No analysis state found.[/red] Run `analyze` first.")
        sys.exit(1)

    with StateDB(db_path) as db:
        meta = db.get_all_metadata()
        counts = db.get_total_counts()
        progress = db.get_progress()

        # Header
        console.print()
        console.print(f"[bold]Repository:[/bold] {meta.get('repo_path', 'unknown')}")
        console.print(f"[bold]Model:[/bold] {meta.get('model', 'unknown')}")
        console.print(f"[bold]Started:[/bold] {meta.get('started_at', 'unknown')}")
        if meta.get("last_resumed_at"):
            console.print(f"[bold]Last resumed:[/bold] {meta['last_resumed_at']}")
        console.print()

        # Progress table
        table = Table(title="Progress")
        table.add_column("Status", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")

        total = counts["total"]
        for label, count in [
            ("Completed", counts["completed"]),
            ("In Progress", counts["in_progress"]),
            ("Flagged for Opus", counts["flagged"]),
            ("Errors", counts["errors"]),
            ("Removed", counts["removed"]),
        ]:
            pct = f"{count/total*100:.1f}%" if total else "—"
            style = ""
            if label == "Completed":
                style = "green"
            elif label == "Errors":
                style = "red"
            elif label == "Flagged for Opus":
                style = "yellow"
            table.add_row(f"[{style}]{label}[/{style}]" if style else label, str(count), pct)

        table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]", "")
        console.print(table)

        # Status breakdown
        if len(progress) > 2:
            console.print()
            detail = Table(title="Detailed Status")
            detail.add_column("Status")
            detail.add_column("Count", justify="right")
            for s, c in sorted(progress.items()):
                detail.add_row(s, str(c))
            console.print(detail)

        console.print()


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--api-key",
    envvar="ANTHROPIC_API_KEY",
    default=None,
    help="Anthropic API key. Can also be set via ANTHROPIC_API_KEY env var.",
)
@click.option(
    "--relationship-model",
    default="claude-sonnet-4-20250514",
    show_default=True,
    help="Claude model to use for relationship mapping.",
)
@click.option(
    "--api-batch-size",
    default=50,
    show_default=True,
    help="Number of files per relationship API call.",
)
@click.option(
    "--export-prompt",
    is_flag=True,
    default=False,
    help="Export a prompt file for use with Claude Code instead of calling the API.",
)
def relationships(output_dir, api_key, relationship_model, api_batch_size, export_prompt):
    """Generate relationship mapping from analyzed files.

    OUTPUT_DIR is the directory containing completed analysis results.
    Requires either --api-key for automated mapping or --export-prompt for
    manual use with Claude Code.
    """
    if not export_prompt and not api_key:
        raise click.UsageError(
            "Either --api-key or --export-prompt is required."
        )
    console.print(f"Mapping relationships in {output_dir}")
    console.print("Not yet implemented.")


@cli.command("resolve-flagged")
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--api-key",
    envvar="ANTHROPIC_API_KEY",
    default=None,
    help="Anthropic API key. Can also be set via ANTHROPIC_API_KEY env var.",
)
@click.option(
    "--export-prompt",
    is_flag=True,
    default=False,
    help="Export a prompt file for use with Claude Code instead of calling the API.",
)
def resolve_flagged(output_dir, api_key, export_prompt):
    """Resolve files that failed quorum using a frontier model.

    OUTPUT_DIR is the directory containing analysis results with flagged files.
    Requires either --api-key for automated resolution or --export-prompt for
    manual use with Claude Code.
    """
    if not export_prompt and not api_key:
        raise click.UsageError(
            "Either --api-key or --export-prompt is required."
        )
    console.print(f"Resolving flagged files in {output_dir}")
    console.print("Not yet implemented.")
