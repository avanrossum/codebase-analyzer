"""CLI entry point for codebase-analyzer."""

import click

from codebase_analyzer import __version__


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
    click.echo(f"Analyzing {repo_path} → {output}")
    click.echo("Not yet implemented.")


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False))
def status(output_dir):
    """Check progress of an analysis run.

    OUTPUT_DIR is the directory containing analysis results and state.
    """
    click.echo(f"Checking status of {output_dir}")
    click.echo("Not yet implemented.")


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
    click.echo(f"Mapping relationships in {output_dir}")
    click.echo("Not yet implemented.")


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
    click.echo(f"Resolving flagged files in {output_dir}")
    click.echo("Not yet implemented.")
