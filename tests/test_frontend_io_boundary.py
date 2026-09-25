from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "caldav_assistant" / "internal"
FRONTEND_ROOTS = (
    ROOT / "cli",
    ROOT / "prompts",
    ROOT / "presentation",
)


def _frontend_python_files():
    for root in FRONTEND_ROOTS:
        yield from root.rglob("*.py")


def test_frontend_has_no_direct_terminal_io_bypass():
    """Terminal implementation details belong only to internal.clients.terminal."""

    violations: list[str] = []
    for path in _frontend_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(ROOT.parent)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"print", "input"}:
                    violations.append(
                        f"{relative}:{node.lineno}: direct {node.func.id}()"
                    )
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "getpass"
                    and node.func.attr == "getpass"
                ):
                    violations.append(
                        f"{relative}:{node.lineno}: direct getpass.getpass()"
                    )

            if isinstance(node, ast.Attribute) and node.attr in {
                "stdin",
                "stdout",
                "stderr",
            }:
                violations.append(
                    f"{relative}:{node.lineno}: direct stream attribute .{node.attr}"
                )

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"flush", "isatty"}
            ):
                violations.append(
                    f"{relative}:{node.lineno}: direct terminal call .{node.func.attr}()"
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in {"msvcrt", "select", "getpass"}:
                        violations.append(
                            f"{relative}:{node.lineno}: terminal import {alias.name}"
                        )
            if isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".", 1)[0]
                if module in {"msvcrt", "select", "getpass"}:
                    violations.append(
                        f"{relative}:{node.lineno}: terminal import {node.module}"
                    )

    assert violations == [], "\n".join(violations)
