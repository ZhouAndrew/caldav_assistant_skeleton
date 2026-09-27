#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SETUP = HERE / "setup.sh"
HOST_INSTALL = HERE / "install-native-host.sh"
UPDATE_DEPLOY = HERE / "update-server" / "deploy.sh"
LOG_PATH = Path.home() / ".local" / "state" / "caldav-assistant" / "thunderbird" / "native-host.log"
DESKTOP = Path(os.environ.get("XDG_DESKTOP_DIR", Path.home() / "Desktop"))
MANIFEST = HERE / "manifest.json"

EVENTS: "queue.Queue[tuple[str, object]]" = queue.Queue()


class SetupGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CalDAV Assistant — Thunderbird Setup")
        self.geometry("820x620")
        self.minsize(720, 520)

        self.running = False
        self.status_var = tk.StringVar(value="Ready")
        self.version_var = tk.StringVar(value=self._version())
        self.server_var = tk.StringVar(value="Checking…")
        self.host_var = tk.StringVar(value="Checking…")
        self.log_var = tk.StringVar(value="Checking…")

        self._build()
        self.after(100, self._drain_events)
        self.after(250, self.refresh_status)

    def _version(self) -> str:
        try:
            return str(json.loads(MANIFEST.read_text(encoding="utf-8"))["version"])
        except Exception:
            return "unknown"

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="CalDAV Assistant · Thunderbird",
            font=("Sans", 18, "bold"),
        )
        title.pack(anchor="w")
        ttk.Label(
            outer,
            text="One-click install, repair, verification, and logs. No browser required.",
        ).pack(anchor="w", pady=(2, 14))

        status = ttk.LabelFrame(outer, text="Status", padding=10)
        status.pack(fill="x")
        rows = [
            ("Extension", self.version_var),
            ("Update server", self.server_var),
            ("Native Host", self.host_var),
            ("Logs", self.log_var),
        ]
        for row, (name, var) in enumerate(rows):
            ttk.Label(status, text=name + ":").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            ttk.Label(status, textvariable=var).grid(row=row, column=1, sticky="w", pady=2)
        status.columnconfigure(1, weight=1)

        actions = ttk.LabelFrame(outer, text="Actions", padding=10)
        actions.pack(fill="x", pady=(12, 0))

        self.primary = ttk.Button(
            actions,
            text="Install / Update Everything",
            command=lambda: self.run_command(
                "Full install / update",
                ["bash", str(SETUP), "--all"],
            ),
        )
        self.primary.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)

        self.host_button = ttk.Button(
            actions,
            text="Repair Native Host",
            command=lambda: self.run_command(
                "Repair Native Host",
                ["bash", str(HOST_INSTALL)],
            ),
        )
        self.host_button.grid(row=1, column=0, sticky="ew", padx=4, pady=4)

        self.server_button = ttk.Button(
            actions,
            text="Repair Update Server",
            command=lambda: self.run_command(
                "Repair update server",
                ["bash", str(UPDATE_DEPLOY)],
            ),
        )
        self.server_button.grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        self.verify_button = ttk.Button(
            actions,
            text="Verify Everything",
            command=lambda: self.run_command(
                "Verify integration",
                ["bash", str(SETUP), "--verify"],
            ),
        )
        self.verify_button.grid(row=2, column=0, sticky="ew", padx=4, pady=4)

        self.open_log_button = ttk.Button(
            actions,
            text="Open Log Folder",
            command=self.open_log_folder,
        )
        self.open_log_button.grid(row=2, column=1, sticky="ew", padx=4, pady=4)

        self.refresh_button = ttk.Button(actions, text="Refresh Status", command=self.refresh_status)
        self.refresh_button.grid(row=3, column=0, sticky="ew", padx=4, pady=4)

        self.desktop_button = ttk.Button(actions, text="Open Desktop XPI", command=self.open_desktop)
        self.desktop_button.grid(row=3, column=1, sticky="ew", padx=4, pady=4)

        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        output_frame = ttk.LabelFrame(outer, text="Live output", padding=8)
        output_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.output = scrolledtext.ScrolledText(
            output_frame,
            height=16,
            wrap="word",
            font=("Monospace", 10),
        )
        self.output.pack(fill="both", expand=True)
        self.output.configure(state="disabled")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")

        self.action_buttons = [
            self.primary,
            self.host_button,
            self.server_button,
            self.verify_button,
            self.refresh_button,
        ]

    def append(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        for button in self.action_buttons:
            button.configure(state=state)

    def run_command(self, label: str, command: list[str]) -> None:
        if self.running:
            return
        self.set_running(True)
        self.status_var.set(label + "…")
        self.append(f"\n== {label} ==\n$ {' '.join(command)}\n")

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    EVENTS.put(("output", line))
                code = proc.wait()
                EVENTS.put(("done", (label, code)))
            except Exception as exc:
                EVENTS.put(("error", (label, exc)))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_status(self) -> None:
        if self.running:
            return

        def worker() -> None:
            service = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "is-active",
                    "--quiet",
                    "caldav-assistant-thunderbird-update-server.service",
                ],
                check=False,
            )
            launcher = Path.home() / ".local" / "bin" / "caldav-assistant-thunderbird-host-experimental"
            if LOG_PATH.is_file() and os.access(LOG_PATH, os.R_OK):
                log_text = f"Readable · {LOG_PATH.stat().st_size} bytes"
            else:
                log_text = "Not reachable"
            EVENTS.put(
                (
                    "status",
                    {
                        "server": "Running" if service.returncode == 0 else "Not running",
                        "host": "Installed" if launcher.is_file() else "Missing",
                        "log": log_text,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def open_log_folder(self) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.touch(exist_ok=True)
        subprocess.Popen(["xdg-open", str(LOG_PATH.parent)])

    def open_desktop(self) -> None:
        DESKTOP.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(DESKTOP)])

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = EVENTS.get_nowait()
                if kind == "output":
                    self.append(str(payload))
                elif kind == "done":
                    label, code = payload
                    self.set_running(False)
                    if code == 0:
                        self.status_var.set(label + ": OK")
                        self.append(f"== {label}: OK ==\n")
                    else:
                        self.status_var.set(f"{label}: failed (exit {code})")
                        self.append(f"== {label}: FAILED (exit {code}) ==\n")
                        messagebox.showerror(
                            "CalDAV Assistant",
                            f"{label} failed. The full output is visible below.",
                        )
                    self.refresh_status()
                elif kind == "error":
                    label, exc = payload
                    self.set_running(False)
                    self.status_var.set(label + ": failed")
                    self.append(f"ERROR: {exc}\n")
                    messagebox.showerror("CalDAV Assistant", f"{label} failed:\n{exc}")
                    self.refresh_status()
                elif kind == "status":
                    status = payload
                    self.server_var.set(str(status["server"]))
                    self.host_var.set(str(status["host"]))
                    self.log_var.set(str(status["log"]))
        except queue.Empty:
            pass
        self.after(100, self._drain_events)


def main() -> int:
    app = SetupGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
