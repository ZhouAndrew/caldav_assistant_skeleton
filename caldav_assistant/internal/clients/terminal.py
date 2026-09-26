"""Terminal client I/O adapter.

MODULE CONTRACT
- Imports/calls: stdlib terminal streams and injected presentation callables only.
- Provides: ``StdConsoleIO`` and ``TerminalBellProfile``.
- Must not: parse commands, know Task/Event business rules, access Core services,
  CalDAV, SQLite, IPC, or localization policy.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import getpass
import os
import shutil
import sys
from threading import Event
from time import sleep
from typing import Any, Callable, TextIO


@dataclass(frozen=True, slots=True)
class TerminalBellProfile:
    """Injected presentation policy for one logical terminal reminder bell."""

    enabled: Callable[[], bool]
    repeat_count: Callable[[], int]
    interval_ms: Callable[[], int]


class _BellAwareTextStream:
    """Transparent stream wrapper that turns one BEL into a persistent reminder alarm.

    ``repeat_count`` is the number of rings in one burst. Bursts repeat until the
    human presses Ctrl-C. The Ctrl-C is consumed here: acknowledging the alarm must
    not accidentally pause, complete, or otherwise mutate the current Task.
    """

    def __init__(
        self,
        stream: TextIO,
        profile: TerminalBellProfile,
        *,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._stream = stream
        self._profile = profile
        self._sleep_fn = sleep_fn

    @staticmethod
    def _read_setting(provider: Callable[[], Any], default: Any) -> Any:
        try:
            return provider()
        except Exception:
            return default

    def _ring_once_logically(self) -> int:
        """Ring in configured bursts until Ctrl-C acknowledges this reminder."""
        terminal_bell_enabled = bool(
            self._read_setting(self._profile.enabled, True)
        )
        if not terminal_bell_enabled:
            return 0

        try:
            rings_per_burst = max(
                1,
                int(self._read_setting(self._profile.repeat_count, 3)),
            )
        except (TypeError, ValueError):
            rings_per_burst = 3
        try:
            pause_between_rings_ms = max(
                100,
                int(self._read_setting(self._profile.interval_ms, 400)),
            )
        except (TypeError, ValueError):
            pause_between_rings_ms = 400

        pause_between_rings_seconds = pause_between_rings_ms / 1000.0
        pause_between_bursts_seconds = max(
            0.8,
            pause_between_rings_seconds * 2.0,
        )
        rings_sounded = 0

        self._stream.write("\n🔔 Reminder alarm — press Ctrl-C to stop the ringing.\n")
        self._stream.flush()
        try:
            while True:
                for ring_number in range(rings_per_burst):
                    self._stream.write("\a")
                    self._stream.flush()
                    rings_sounded += 1
                    is_last_ring_in_burst = ring_number + 1 >= rings_per_burst
                    if not is_last_ring_in_burst:
                        self._sleep_fn(pause_between_rings_seconds)
                self._sleep_fn(pause_between_bursts_seconds)
        except KeyboardInterrupt:
            self._stream.write("\n✓ Reminder alarm stopped. Task/Event state was not changed.\n")
            self._stream.flush()
            return rings_sounded

    def write(self, value: str) -> int:
        text = str(value)
        if "\a" not in text:
            return self._stream.write(text)

        text_parts = text.split("\a")
        for part_number, text_part in enumerate(text_parts):
            if text_part:
                self._stream.write(text_part)
            has_bell_after_part = part_number + 1 < len(text_parts)
            if has_bell_after_part:
                self._ring_once_logically()
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class StdConsoleIO:
    """Tiny line-oriented console adapter shared by REPL, Menu and PromptKit.

    ``push_line()`` is a presentation-only pushback primitive. It lets a nested
    navigation menu hand an arbitrary line back to the ordinary REPL parser instead
    of swallowing it as an invalid menu choice.

    ``waiting_for_input`` is presentation state, not application state.  It allows a
    live-progress renderer to distinguish "Core is still working" from "the program
    has already displayed a menu and is waiting for the human".  Without this bit a
    worker-hosted prompt produced endless fake ``Still working`` heartbeats while the
    user was simply deciding what to choose.

    A ``TerminalBellProfile`` may be injected by the composition root. The rest of
    the CLI emits one ordinary ``\\a`` for one logical reminder. This adapter turns
    that logical alert into repeated, human-configured bell bursts and keeps repeating
    them until Ctrl-C acknowledges the reminder. Acknowledgement is presentation-only
    and deliberately does not become a Task/Event lifecycle command.
    """

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        secret_fn: Callable[[str], str] | None = None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        terminal_width_fn: Callable[[], int] | None = None,
        ui_key_fn: Callable[[], str] | None = None,
        terminal_bell_profile: TerminalBellProfile | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._input_fn = input_fn
        self._secret_fn = secret_fn
        self.stdin = stdin or sys.stdin
        self._terminal_width_fn = terminal_width_fn
        self._ui_key_fn = ui_key_fn
        self._panel_active = False
        self._windows_vt_enabled: bool | None = None
        output_stream = stdout or sys.stdout
        self.stdout = (
            _BellAwareTextStream(
                output_stream,
                terminal_bell_profile,
                sleep_fn=sleep_fn,
            )
            if terminal_bell_profile is not None
            else output_stream
        )
        self.stderr = stderr or sys.stderr
        self._pending_lines: deque[str] = deque()
        self._input_wait = Event()

    @property
    def waiting_for_input(self) -> bool:
        return self._input_wait.is_set()

    @property
    def supports_line_polling(self) -> bool:
        """Whether poll_input() can return a complete typed command line."""
        return os.name != "nt"

    def supports_readline_completion(self) -> bool:
        """Return whether readline should attach to the real interactive stdin."""
        if self._input_fn is not None:
            return False
        isatty = getattr(self.stdin, "isatty", None)
        return bool(callable(isatty) and isatty())

    def is_interactive(self) -> bool:
        isatty = getattr(self.stdout, "isatty", None)
        return bool(callable(isatty) and isatty())

    def display_width(self) -> int | None:
        """Return usable terminal columns only for an interactive terminal."""
        if self._terminal_width_fn is not None:
            try:
                return max(20, int(self._terminal_width_fn()))
            except Exception:
                return None
        if not self.is_interactive():
            return None
        try:
            return max(20, int(shutil.get_terminal_size(fallback=(80, 24)).columns))
        except OSError:
            return 80

    def supports_interactive_picker(self) -> bool:
        """Whether this client can drive key-oriented picker widgets."""
        if self._ui_key_fn is not None:
            return True
        if self._input_fn is not None:
            return False
        input_tty = getattr(self.stdin, "isatty", None)
        output_tty = getattr(self.stdout, "isatty", None)
        return bool(
            callable(input_tty)
            and input_tty()
            and callable(output_tty)
            and output_tty()
        )

    def _enable_windows_vt(self) -> bool:
        if os.name != "nt":
            return True
        if self._windows_vt_enabled is not None:
            return self._windows_vt_enabled
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                self._windows_vt_enabled = False
                return False
            enabled = int(mode.value) | 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            self._windows_vt_enabled = bool(kernel32.SetConsoleMode(handle, enabled))
        except Exception:
            self._windows_vt_enabled = False
        return bool(self._windows_vt_enabled)

    def begin_interactive_panel(self) -> None:
        """Enter a redraw-friendly terminal panel without leaking ANSI upward."""
        if self._panel_active:
            return
        self._panel_active = True
        if self.is_interactive() and self._enable_windows_vt():
            self.stdout.write("\x1b[?1049h\x1b[H")
            self.stdout.flush()

    def end_interactive_panel(self) -> None:
        if not self._panel_active:
            return
        if self.is_interactive() and self._enable_windows_vt():
            self.stdout.write("\x1b[?1049l")
            self.stdout.flush()
        self._panel_active = False

    def _render_panel_lines(self, lines: list[str]) -> None:
        text = "\n".join(str(line) for line in lines)
        if self.is_interactive() and self._enable_windows_vt():
            self.stdout.write("\x1b[H" + text + "\x1b[J")
            self.stdout.flush()
            return
        self.write(text)

    def _calendar_lines(self, view: Any) -> list[str]:
        marked = set(getattr(view, "marked_dates", ()) or ())
        selected = getattr(view, "selected")
        today = getattr(view, "today")
        month = selected.month
        lines = [f"        < {view.month_label} >", " Mon  Tue  Wed  Thu  Fri  Sat  Sun"]
        for week in view.weeks:
            cells = []
            for day in week:
                if day.month != month:
                    cell = "    "
                elif day == selected:
                    cell = f"[{day.day:2d}]"
                elif day in marked:
                    cell = f" {day.day:2d}•"
                elif day == today:
                    cell = f"*{day.day:2d} "
                else:
                    cell = f" {day.day:2d} "
                cells.append(cell)
            lines.append(" ".join(cells).rstrip())
        return lines

    @staticmethod
    def _truncate_terminal_text(text: str, width: int) -> str:
        from ..presentation.renderers import _display_width

        value = str(text)
        if width <= 1 or _display_width(value) <= width:
            return value
        suffix = "…"
        target = max(1, width - 1)
        result = ""
        for char in value:
            if _display_width(result + char) > target:
                break
            result += char
        return result + suffix

    def render_date_picker(self, view: Any) -> None:
        lines = [str(getattr(view, "title", "Choose date")), ""]
        lines.extend(self._calendar_lines(view))
        lines.extend(
            [
                "",
                f"Selected: {view.selected.isoformat()}",
                "←/→ day · ↑/↓ week · PgUp/PgDn month · Enter choose · i input · t today · q cancel",
            ]
        )
        self._render_panel_lines(lines)

    def render_scrollable_list(self, view: Any, *, footer: str = "") -> None:
        """Render a generic scrollable selector."""
        lines = [str(view.title), ""]
        labels = view.visible_labels
        start = view.offset
        selected_visible = view.visible_selected_index
        width = max(24, int(self.display_width() or 80) - 8)
        if not labels:
            lines.append("  (No choices)")
        else:
            for visible_index, label in enumerate(labels):
                number = start + visible_index + 1
                pointer = ">" if visible_index == selected_visible else " "
                shown = self._truncate_terminal_text(str(label), width)
                lines.append(f"{pointer} {number:>2}. {shown}")
        total = len(view.labels)
        if total > view.page_size:
            first = view.offset + 1
            last = min(total, view.offset + view.page_size)
            lines.append(f"  showing {first}-{last} of {total}")
        if footer:
            lines.extend(["", str(footer)])
        self._render_panel_lines(lines)

    def render_task_picker(self, view: Any) -> None:
        lines = [str(view.title), ""]
        lines.extend(self._calendar_lines(view.calendar))
        lines.extend(["", str(view.tasks.title)])
        labels = view.tasks.visible_labels
        start = view.tasks.offset
        selected_visible = view.tasks.visible_selected_index
        width = max(24, int(self.display_width() or 80) - 8)
        if not labels:
            lines.append("  (No tasks on this date)")
        else:
            for visible_index, label in enumerate(labels):
                number = start + visible_index + 1
                pointer = ">" if visible_index == selected_visible else " "
                shown = self._truncate_terminal_text(str(label), width)
                lines.append(f"{pointer} {number:>2}. {shown}")
        total = len(view.tasks.labels)
        if total > view.tasks.page_size:
            first = view.tasks.offset + 1
            last = min(total, view.tasks.offset + view.tasks.page_size)
            lines.append(f"  showing {first}-{last} of {total}")
        lines.extend(["", str(view.footer)])
        self._render_panel_lines(lines)

    def read_ui_action(self) -> str:
        """Read one key and translate terminal-specific bytes to a UI action."""
        if self._ui_key_fn is not None:
            return str(self._ui_key_fn())
        if not self.supports_interactive_picker():
            return "unsupported"

        if os.name == "nt":
            import msvcrt

            char = msvcrt.getwch()
            if char in {"\x00", "\xe0"}:
                special = msvcrt.getwch()
                return {
                    "H": "up",
                    "P": "down",
                    "K": "left",
                    "M": "right",
                    "I": "page_up",
                    "Q": "page_down",
                    "G": "home",
                    "O": "end",
                }.get(special, "unknown")
            if char in {"\r", "\n"}:
                return "enter"
            if char == "\x1b":
                return "cancel"
            return {
                "q": "cancel",
                "Q": "cancel",
                "i": "input_date",
                "I": "input_date",
                "t": "today",
                "T": "today",
                "/": "search",
            }.get(char, f"number:{char}" if char.isdigit() else "unknown")

        import select
        import termios
        import tty

        fd = self.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            char = self.stdin.read(1)
            if char in {"\r", "\n"}:
                return "enter"
            if char != "\x1b":
                return {
                    "q": "cancel",
                    "Q": "cancel",
                    "i": "input_date",
                    "I": "input_date",
                    "t": "today",
                    "T": "today",
                    "/": "search",
                }.get(char, f"number:{char}" if char.isdigit() else "unknown")

            sequence = ""
            for _ in range(4):
                ready, _, _ = select.select([self.stdin], [], [], 0.03)
                if not ready:
                    break
                sequence += self.stdin.read(1)
                if sequence.endswith("~") or sequence in {"[A", "[B", "[C", "[D"}:
                    break
            return {
                "[A": "up",
                "[B": "down",
                "[C": "right",
                "[D": "left",
                "[5~": "page_up",
                "[6~": "page_down",
                "[H": "home",
                "[F": "end",
                "OH": "home",
                "OF": "end",
            }.get(sequence, "cancel" if not sequence else "unknown")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def push_line(self, value: Any) -> None:
        """Make one line the next value returned by read() without parsing it."""
        self._pending_lines.appendleft(str(value))

    def read(self, prompt: str = "") -> str:
        if self._pending_lines:
            return self._pending_lines.popleft()
        reader = self._input_fn or input
        self._input_wait.set()
        try:
            return reader(prompt)
        finally:
            self._input_wait.clear()

    def ask_secret(self, prompt: str = "Password") -> str:
        """Read a secret with terminal echo disabled."""
        label = str(prompt)
        if label and not label.endswith((" ", ": ")):
            label += ": "
        reader = self._secret_fn
        if reader is not None:
            return str(reader(label))
        return getpass.getpass(label, stream=self.stderr)

    def write(self, value: Any = "", *, end: str = "\n") -> None:
        print(value, file=self.stdout, end=end, flush=True)

    def error(self, value: Any, *, end: str = "\n") -> None:
        print(value, file=self.stderr, end=end, flush=True)

    def bell(self) -> None:
        """Emit one logical terminal alert through the terminal stream wrapper."""
        self.stdout.write("\a")
        self.stdout.flush()

    def render_menu(self, view: Any) -> None:
        """Render one MenuView using terminal width, then write through this adapter."""
        from ..presentation import TextRenderer

        renderer = TextRenderer(max_width=self.display_width())
        for line in renderer.render_lines(view):
            self.write(line)

    def update_line(self, text: Any, previous_width: int = 0) -> int:
        """Refresh one terminal line in place; redirected output is emitted once."""
        value = str(text)
        previous = max(0, int(previous_width))
        if self.is_interactive():
            padded = value.ljust(previous)
            self.stdout.write("\r" + padded)
            self.stdout.flush()
            return max(previous, len(value))
        if previous == 0:
            self.write(value)
        return max(previous, len(value))

    def clear_line(self, previous_width: int) -> None:
        """Clear an in-place terminal line without leaking control codes upward."""
        previous = max(0, int(previous_width))
        if not previous or not self.is_interactive():
            return
        self.stdout.write("\r" + (" " * previous) + "\r")
        self.stdout.flush()

    def poll_input(self) -> str | None:
        """Poll terminal input without blocking live refresh."""
        if os.name == "nt":
            try:
                import msvcrt
            except ImportError:
                return None
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char in {"\r", "\n"}:
                return ""
            return char

        try:
            import select
            ready, _, _ = select.select([self.stdin], [], [], 0)
        except (OSError, ValueError, TypeError):
            return None
        if not ready:
            return None
        line = self.stdin.readline()
        if line == "":
            return "q"
        return line.rstrip("\r\n")

    prompt = read
    input = read
    output = write
    show = write


__all__ = ["StdConsoleIO", "TerminalBellProfile"]
