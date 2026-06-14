"""Build the rulebook vector index (Qdrant + voyage-3-large).

Usage: uv run python -m scripts.build_index
"""

from __future__ import annotations

import typer

from compliance_agent.rulebook.indexer import RulebookIndexer

app = typer.Typer(add_completion=False)


@app.command()
def main() -> None:
    """Embed every rule clause and upsert into Qdrant."""
    count = RulebookIndexer().build()
    typer.echo(f"Indexed {count} rules into the rulebook collection.")


if __name__ == "__main__":
    app()
