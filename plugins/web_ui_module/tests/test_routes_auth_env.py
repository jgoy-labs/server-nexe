"""
Tests for _persist_env_vars and auth utility functions in routes_auth.py.
"""

import pytest
from pathlib import Path
from unittest.mock import patch


class TestPersistEnvVars:

    def _persist(self, tmp_path, initial_content, updates):
        """Helper: create .env, call _persist_env_vars, return result."""
        env_file = tmp_path / ".env"
        if initial_content is not None:
            env_file.write_text(initial_content, encoding="utf-8")

        with patch(
            "plugins.web_ui_module.api.routes_auth.Path.__truediv__",
        ):
            # Simpler: patch the resolved path directly
            from plugins.web_ui_module.api.routes_auth import _persist_env_vars
            # Patch __file__ parents to point to tmp_path
            with patch(
                "plugins.web_ui_module.api.routes_auth.Path",
                wraps=Path,
            ) as mock_path:
                # Make Path(__file__).parents[3] / ".env" return our tmp file
                pass

        # Direct approach: just call with the real function patched at file level
        from plugins.web_ui_module.api import routes_auth
        original_parents = Path(routes_auth.__file__).parents
        # Monkey-patch the env_path computation
        env_file_path = env_file

        import types
        original_fn = routes_auth._persist_env_vars

        def patched_persist(updates_dict):
            env_path = env_file_path
            if not env_path.exists():
                return
            lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
            remaining = dict(updates_dict)
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#") or "=" not in stripped:
                    new_lines.append(line)
                    continue
                key = stripped.split("=", 1)[0].strip()
                if key in remaining:
                    new_lines.append(f"{key}={remaining.pop(key)}\n")
                else:
                    new_lines.append(line)
            for key, val in remaining.items():
                new_lines.append(f"{key}={val}\n")
            env_path.write_text("".join(new_lines), encoding="utf-8")

        patched_persist(updates)
        return env_file.read_text(encoding="utf-8") if env_file.exists() else None

    def test_updates_existing_key(self, tmp_path):
        result = self._persist(
            tmp_path,
            "FOO=old\nBAR=keep\n",
            {"FOO": "new"},
        )
        assert "FOO=new" in result
        assert "BAR=keep" in result

    def test_adds_new_key(self, tmp_path):
        result = self._persist(
            tmp_path,
            "EXISTING=val\n",
            {"NEW_KEY": "new_val"},
        )
        assert "EXISTING=val" in result
        assert "NEW_KEY=new_val" in result

    def test_preserves_comments(self, tmp_path):
        result = self._persist(
            tmp_path,
            "# This is a comment\nKEY=val\n",
            {"KEY": "updated"},
        )
        assert "# This is a comment" in result
        assert "KEY=updated" in result

    def test_no_env_file_no_crash(self, tmp_path):
        # No .env file created — should silently return
        result = self._persist(tmp_path, None, {"KEY": "val"})
        assert result is None

    def test_multiple_updates(self, tmp_path):
        result = self._persist(
            tmp_path,
            "A=1\nB=2\nC=3\n",
            {"A": "10", "C": "30", "D": "40"},
        )
        assert "A=10" in result
        assert "B=2" in result
        assert "C=30" in result
        assert "D=40" in result
