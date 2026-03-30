"""Basic CLI smoke tests."""

from click.testing import CliRunner

from codebase_analyzer.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Analyze codebases" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_analyze_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.output
    assert "--model" in result.output
    assert "--profiles" in result.output


def test_status_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0


def test_relationships_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["relationships", "--help"])
    assert result.exit_code == 0
    assert "--api-key" in result.output
    assert "--export-prompt" in result.output


def test_resolve_flagged_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["resolve-flagged", "--help"])
    assert result.exit_code == 0
    assert "--api-key" in result.output
    assert "--export-prompt" in result.output
