"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/__main__.py
Description: CLI entry point for the llama_cpp module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

try:
    import typer  # noqa: F401  # guard: friendly error if typer is missing
except ImportError:
    import sys
    print("CLI requires typer: pip install typer", file=sys.stderr)
    sys.exit(1)

from plugins._shared.cli_scaffold import build_module_cli
from .manifest import get_module_instance  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]  # FP: install_lazy_manifest() injects get_module_instance dynamically
from .health import get_health

app = build_module_cli(
    help_text="Llama.cpp module CLI — Server Nexe",
    location=__file__,
    workflow_msg="Llama.cpp workflow nodes: (stub — Part 2)",
    get_module_instance=get_module_instance,
    get_health=get_health,
)


if __name__ == "__main__":
    app()
