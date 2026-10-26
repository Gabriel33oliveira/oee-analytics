"""Run the CLI commands and Python snippets shown in README.md."""

import re
import shlex
import shutil
from pathlib import Path

from oee_analytics import cli

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _blocks(language: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", README, flags=re.DOTALL)


def _commands() -> list[str]:
    return [
        line[len("$ oee "):]
        for block in _blocks("console")
        for line in block.splitlines()
        if line.startswith("$ oee ")
    ]


def test_readme_has_required_sections():
    headings = {h.lower() for h in re.findall(r"^## (.+)$", README, flags=re.MULTILINE)}
    for section in (
        "overview",
        "oee formulas",
        "input formats",
        "setup",
        "cli usage",
        "python api",
        "architecture",
        "assumptions and limitations",
        "testing",
    ):
        assert section in headings, section


def test_readme_examples_run(tmp_path, monkeypatch, capsys):
    shutil.copytree(ROOT / "examples" / "sample_data", tmp_path / "examples" / "sample_data")
    monkeypatch.chdir(tmp_path)

    commands = _commands()
    assert {c.split()[0] for c in commands} == {"generate", "summary", "pareto", "compare", "report"}
    for command in commands:
        assert cli.main(shlex.split(command)) == 0, command
    assert (tmp_path / "report.html").is_file()

    snippets = _blocks("python")
    assert snippets
    for code in snippets:
        exec(compile(code, "README.md", "exec"), {})
    assert "Plant OEE: 61.9%" in capsys.readouterr().out


def test_readme_sample_output_matches_cli(tmp_path, monkeypatch, capsys):
    """The `summary` table in the README is the real output for the seed-42 dataset."""
    monkeypatch.chdir(tmp_path)
    cli.main(["generate", "--out", "data/plant", "--days", "7", "--seed", "42"])
    capsys.readouterr()
    cli.main(["summary", "data/plant"])
    assert capsys.readouterr().out.strip() in README
