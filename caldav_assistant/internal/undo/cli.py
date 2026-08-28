"""CLI composition for the internal unified UndoManager runtime route."""
from __future__ import annotations

from typing import Any

from ...api.v1.errors import ValidationError


def register_undo_cli_command(commands: Any, runtime: Any) -> None:
    """Register protected ``undo`` without exposing IPC in the public Python API."""

    def undo(*parts: Any) -> Any:
        if parts:
            raise ValidationError("undo does not take arguments")
        return runtime.call("undo.last")

    if "undo" not in commands.registry:
        commands.register_builtin(
            "undo",
            undo,
            description="Undo the most recent reversible Task/Event change.",
        )


__all__ = ["register_undo_cli_command"]
