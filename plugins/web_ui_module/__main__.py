"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/__main__.py
Description: CLI entry point for the web_ui module.

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
    """Show web_ui module information."""
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]  # FP: install_lazy_manifest() injects get_module_instance dynamically
    module = get_module_instance()
    data = module.get_info()
    for k, v in data.items():
        typer.echo(f"{k}: {v}")


@app.command()
def health():
    """Show health status."""
    from .health import get_health
    result = get_health()
    typer.echo(f"Status: {result.get('status', 'unknown')}")


@app.command()
def test():
    """Run module tests."""
    import subprocess
    import sys
    from pathlib import Path
    test_dir = Path(__file__).parent / "tests"
    result = subprocess.run(  # nosec B603: sys.executable + literal pytest invocation; test_dir is Path(__file__)-derived
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent.parent)
    )
    raise typer.Exit(code=result.returncode)


@app.command()
def workflow():
    """Workflow nodes info."""
    typer.echo("Web UI workflow nodes: (stub — Part 2)")


if __name__ == "__main__":
    app()
