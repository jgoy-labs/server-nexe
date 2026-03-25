"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/__main__.py
Description: Entry point CLI per al modul web_ui.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

try:
    import typer
except ImportError:
    import sys
    print("CLI requires typer: pip install typer", file=sys.stderr)
    sys.exit(1)

app = typer.Typer(help="Web UI module CLI — Server Nexe")


@app.command()
def info():
    """Mostra informacio del modul web_ui."""
    from .manifest import get_module_instance
    module = get_module_instance()
    data = module.get_info()
    for k, v in data.items():
        typer.echo(f"{k}: {v}")


@app.command()
def health():
    """Mostra l'estat de salut."""
    from .health import get_health
    result = get_health()
    typer.echo(f"Status: {result.get('status', 'unknown')}")


@app.command()
def test():
    """Executa tests del modul."""
    import subprocess, sys
    from pathlib import Path
    test_dir = Path(__file__).parent / "tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent.parent)
    )
    raise typer.Exit(code=result.returncode)


@app.command()
def workflow():
    """Info de workflow nodes."""
    typer.echo("Web UI workflow nodes: (stub — Part 2)")


if __name__ == "__main__":
    app()
