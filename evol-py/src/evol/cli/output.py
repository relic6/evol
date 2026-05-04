"""Rich-based output helpers for the EVOL CLI.

Centralizing styling here keeps individual command modules tiny.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

_console = Console()


def info(msg: str) -> None:
    _console.print(f"[bold cyan]>[/bold cyan] {msg}")


def success(msg: str) -> None:
    _console.print(f"[bold green]✓[/bold green] {msg}")


def warn(msg: str) -> None:
    _console.print(f"[bold yellow]![/bold yellow] {msg}")


def error(msg: str) -> None:
    _console.print(f"[bold red]✗[/bold red] {msg}")


def kv_table(title: str, data: dict[str, Any]) -> None:
    table = Table(
        title=title,
        title_style="bold",
        show_header=False,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("key", style="dim", justify="right")
    table.add_column("value")
    for k, v in data.items():
        table.add_row(str(k), _stringify(v))
    _console.print(table)


def list_table(title: str, header: list[str], rows: list[list[Any]]) -> None:
    table = Table(title=title, title_style="bold")
    for h in header:
        table.add_column(h)
    for row in rows:
        table.add_row(*[_stringify(v) for v in row])
    _console.print(table)


def _stringify(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(map(str, v)) if v else "—"
    return str(v)


__all__ = [
    "error",
    "info",
    "kv_table",
    "list_table",
    "success",
    "warn",
]
