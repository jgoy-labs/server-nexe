"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/cli/main.py
Description: CLI del modul security amb 4 comandes standard.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

try:
    import typer
except ImportError:
    import sys
    print("CLI requires typer: pip install typer", file=sys.stderr)
    sys.exit(1)

app = typer.Typer(help="Security module CLI — Server Nexe")


@app.command()
def info():
    """Mostra informacio del modul security."""
    from plugins.security.manifest import get_module_instance
    module = get_module_instance()
    data = module.get_info()
    typer.echo(f"Name:        {data['name']}")
    typer.echo(f"Version:     {data['version']}")
    typer.echo(f"Type:        {data['type']}")
    typer.echo(f"Initialized: {data['initialized']}")
    typer.echo(f"Description: {data['description']}")
    typer.echo(f"Endpoints:   {', '.join(data['endpoints'])}")


@app.command()
def health():
    """Mostra l'estat de salut del modul security."""
    from plugins.security.health import get_health
    result = get_health()
    status = result.get("status", "unknown")
    typer.echo(f"Status:  {status}")
    typer.echo(f"Message: {result.get('message', '-')}")
    checks = result.get("checks", [])
    if checks:
        typer.echo("Checks:")
        for c in checks:
            icon = "OK" if c.get("status") == "ok" else c.get("status", "?").upper()
            typer.echo(f"  [{icon}] {c.get('name', '?')}: {c.get('message', '-')}")


@app.command()
def test():
    """Executa tests del modul security."""
    import subprocess
    import sys
    from pathlib import Path

    test_dir = Path(__file__).parent.parent / "tests"
    typer.echo(f"Running tests from {test_dir}...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent.parent.parent)
    )
    raise typer.Exit(code=result.returncode)


@app.command()
def workflow():
    """Informacio de workflow nodes del modul security."""
    typer.echo("Security workflow nodes:")
    typer.echo("  - sanitizer/workflow/nodes/sanitizer_node.py")
    typer.echo("  - sanitizer/workflow/nodes/intervention_node.py")
    typer.echo("  - workflow/ (stub — funcional a Part 2)")
