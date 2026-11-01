"""`q3tui`: open the project of the current folder in the TUI (spec/cli.md: the CLI comes later)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from q3tui.config import ConfigError


@click.command()
@click.option("--config", "-c", "options", multiple=True, metavar="KEY=VALUE",
              help="Set a config key for this session (the session layer), e.g. --config llm.effort=high")
@click.argument("folder", required=False, type=click.Path(file_okay=False, path_type=Path))
def main(options: tuple[str, ...], folder: Path | None) -> None:
    """Open the project of FOLDER (default: the current folder) in the TUI."""
    from q3tui.runtime.session import open_project

    try:
        opened = open_project(folder or Path.cwd(), session=list(options))
    except ConfigError as exc:  # a config with an error stops Q3TUI before the TUI appears
        click.echo(f"q3tui: {exc}", err=True)
        sys.exit(2)
    from q3tui.tui.app import Q3App
    from q3tui.tui.terminal_keys import enable_alt_menu_keys

    enable_alt_menu_keys()
    Q3App(opened, session=list(options)).run()


if __name__ == "__main__":
    main()
