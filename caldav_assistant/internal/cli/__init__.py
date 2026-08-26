"""Line-oriented CLI wiring."""
from .actions import (
    BuiltinActions,
    BuiltinCommand,
    EXIT_REPL,
    builtin_command_specs,
    register_cli_builtin_commands,
)
from .app import (
    ParsedCommand,
    main,
    parse_command_line,
    run_cli,
    run_one_shot,
    run_repl,
)
from .io import StdConsoleIO

__all__ = [
    "BuiltinActions",
    "BuiltinCommand",
    "EXIT_REPL",
    "builtin_command_specs",
    "register_cli_builtin_commands",
    "ParsedCommand",
    "parse_command_line",
    "run_one_shot",
    "run_repl",
    "run_cli",
    "main",
    "StdConsoleIO",
]
