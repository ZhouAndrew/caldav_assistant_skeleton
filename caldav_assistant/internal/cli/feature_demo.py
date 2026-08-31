"""Read-only live feature demo and fault-localisation command.

The demo deliberately behaves like a normal CLI user: every probe goes through the
same Command/Object API namespaces used by the foreground client.  It never reaches
into SQLite, CalDAV XML, or adapter internals and it never mutates Task/Event/WordPress
data.  The point is to find the first layer that is unavailable or visibly slow while
leaving real user data untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable


_SLOW_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class DemoProbe:
    name: str
    status: str
    elapsed: float
    detail: str = ""
    error: str = ""
    reproduce: str = ""


def _show(ctx: Any, value: Any = "") -> None:
    show = getattr(getattr(ctx, "ui", None), "show", None)
    if callable(show):
        show(value)


def _count(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return len(tuple(value))


def _summary(value: Any) -> str:
    if value is None:
        return "none"
    text = str(getattr(value, "summary", "") or "").strip()
    if text:
        return text
    value_id = str(getattr(value, "id", "") or "").strip()
    return value_id or value.__class__.__name__


def _probe(
    ctx: Any,
    name: str,
    action: Callable[[], Any],
    *,
    detail: Callable[[Any], str] | None = None,
    reproduce: str = "",
) -> tuple[DemoProbe, Any]:
    _show(ctx, f"→ {name}…")
    started = monotonic()
    try:
        value = action()
    except Exception as exc:
        elapsed = monotonic() - started
        text = f"{type(exc).__name__}: {exc}"
        _show(ctx, f"✗ {name} — FAIL ({elapsed:.2f}s)")
        _show(ctx, f"  {text}")
        return DemoProbe(name, "FAIL", elapsed, error=text, reproduce=reproduce), None

    elapsed = monotonic() - started
    status = "SLOW" if elapsed >= _SLOW_SECONDS else "PASS"
    marker = "!" if status == "SLOW" else "✓"
    extra = ""
    if detail is not None:
        try:
            extra = str(detail(value) or "").strip()
        except Exception:
            extra = ""
    suffix = f" — {extra}" if extra else ""
    _show(ctx, f"{marker} {name} — {status} ({elapsed:.2f}s){suffix}")
    return DemoProbe(name, status, elapsed, detail=extra, reproduce=reproduce), value


def _skip(ctx: Any, name: str, reason: str, *, reproduce: str = "") -> DemoProbe:
    _show(ctx, f"- {name} — SKIP — {reason}")
    return DemoProbe(name, "SKIP", 0.0, detail=reason, reproduce=reproduce)


def _caldav_status(settings: Any) -> dict[str, Any]:
    reader = getattr(settings, "caldav_status", None)
    if callable(reader):
        value = reader()
        return dict(value) if isinstance(value, dict) else {"base_url_configured": False}

    # Public/service-side settings contexts do not necessarily expose the CLI-only
    # CalDAV status helper.  Fall back only to a non-secret setting; credentials are
    # intentionally never fetched by this diagnostic.
    getter = getattr(settings, "get", None)
    if not callable(getter):
        return {"base_url_configured": False, "credentials_configured": None}
    return {
        "base_url_configured": bool(getter("caldav.base_url", None)),
        "credentials_configured": None,
    }


def _caldav_status_detail(value: Any) -> str:
    status = dict(value or {})
    server = "configured" if status.get("base_url_configured") else "not configured"
    credentials = status.get("credentials_configured")
    if credentials is True:
        auth = "credentials configured"
    elif credentials is False:
        auth = "credentials not configured"
    else:
        auth = "credential state not exposed"
    source = str(status.get("base_url_source") or "").strip()
    source_text = f"; source={source}" if source else ""
    return f"server {server}; {auth}{source_text}"


def _connection_test(settings: Any) -> Any:
    action = getattr(settings, "test_caldav_connection", None)
    if not callable(action):
        raise AttributeError("CalDAV connection-test helper is not available in this client")
    return action()


def _connection_detail(value: Any) -> str:
    if not isinstance(value, dict):
        return "connection call returned"
    count = int(value.get("collection_count", 0) or 0)
    return f"authenticated; {count} collection(s) visible"


def _command_registry_detail(names: Any) -> str:
    values = {str(name).casefold() for name in (names or ())}
    required = {"today", "next", "current", "start", "pause", "resume", "done", "help", "demo"}
    missing = sorted(required - values)
    if missing:
        return "missing expected action(s): " + ", ".join(missing)
    return f"{len(values)} command/alias name(s) reachable"


def _probe_map(probes: list[DemoProbe]) -> dict[str, DemoProbe]:
    return {probe.name: probe for probe in probes}


def _diagnosis(probes: list[DemoProbe], *, setup_missing: bool) -> list[str]:
    by_name = _probe_map(probes)
    lines: list[str] = []

    ipc = by_name.get("Background / local IPC")
    if ipc is not None and ipc.status == "FAIL":
        return [
            "The foreground CLI started, but the first service call failed. The fault begins at Background Service / local IPC, before CalDAV business logic.",
            "Reproduce with: caldav-assistant background status",
        ]

    if setup_missing:
        lines.append(
            "CalDAV is not configured yet. This is a setup state, not an empty agenda; configure the server and Collection roles before judging Task/Event behavior."
        )
        lines.append("Open: Enter → Settings & setup → CalDAV")

    caldav_test = by_name.get("CalDAV authenticated connection")
    task_read = by_name.get("Task read")
    event_read = by_name.get("Event read")
    agenda = by_name.get("Agenda today")
    next_probe = by_name.get("Next recommendation")

    if caldav_test is not None and caldav_test.status == "FAIL":
        lines.append(
            "Local IPC is reachable, but the authenticated CalDAV path failed. Check server reachability, credentials, discovery, and Collection roles before changing CLI presentation code."
        )
        lines.append("Reproduce with: caldav-assistant settings caldav test")

    raw_reads = [probe for probe in (task_read, event_read) if probe is not None]
    if raw_reads and all(probe.status == "PASS" for probe in raw_reads):
        upper = [probe for probe in (agenda, next_probe) if probe is not None]
        if any(probe.status in {"FAIL", "SLOW"} for probe in upper):
            lines.append(
                "Raw Task/Event reads are healthy but Agenda/Next is slow or failing. The problem is above basic CalDAV reads, in agenda composition/recommendation or that IPC route."
            )
            lines.append("Reproduce with: caldav-assistant today ; caldav-assistant next")

    caldav_io = [probe for probe in (task_read, event_read, caldav_test) if probe is not None]
    if any(probe.status == "SLOW" for probe in caldav_io):
        lines.append(
            "User-visible latency already appears on CalDAV I/O. Fix server/network/adapter/query latency before optimizing menus or terminal rendering."
        )

    activity = by_name.get("Activity Journal read")
    outbox = by_name.get("WordPress Outbox read")
    if any(
        probe is not None and probe.status == "FAIL"
        for probe in (activity, outbox)
    ):
        lines.append(
            "A local Assistant record path failed independently of Task/Event truth. Inspect local Assistant storage/WordPress Outbox rather than rewriting CalDAV Task state."
        )

    failures = [probe for probe in probes if probe.status == "FAIL"]
    slow = [probe for probe in probes if probe.status == "SLOW"]
    if not failures and not slow and not setup_missing:
        lines.append(
            "No fault reproduced on this read-only human path. The timings above are a clean baseline; rerun this command when the user-visible problem is present and compare the first changed stage."
        )
    elif not lines:
        first = (failures or slow)[0]
        lines.append(f"The first abnormal stage is '{first.name}'. Start investigation there instead of treating the whole program as one black box.")
        if first.reproduce:
            lines.append(f"Reproduce with: {first.reproduce}")
    return lines


def _finish_report(ctx: Any, probes: list[DemoProbe], *, setup_missing: bool) -> str:
    counts = {
        status: sum(1 for probe in probes if probe.status == status)
        for status in ("PASS", "SLOW", "FAIL", "SKIP")
    }
    diagnosis = _diagnosis(probes, setup_missing=setup_missing)
    if counts["FAIL"]:
        result = "ISSUE FOUND"
    elif counts["SLOW"]:
        result = "SLOW PATH FOUND"
    elif setup_missing:
        result = "SETUP NEEDED"
    else:
        result = "PASS"

    lines = [
        "",
        f"Live diagnosis result: {result}",
        (
            "Summary: "
            f"{counts['PASS']} pass, {counts['SLOW']} slow, "
            f"{counts['FAIL']} failed, {counts['SKIP']} skipped."
        ),
        "",
        "Likely diagnosis:",
    ]
    lines.extend(f"  - {line}" for line in diagnosis)
    lines.extend(
        [
            "",
            "Safety: read-only; no Task/Event/WordPress data was changed.",
            f"Latency flag: any single stage taking >= {_SLOW_SECONDS:.0f}s is marked SLOW.",
        ]
    )
    return "\n".join(lines)


def run_feature_demo(ctx: Any) -> str:
    """Exercise the real read path, stream timings, and localise the first fault."""
    _show(ctx, "CalDAV Assistant · live feature demo / diagnosis")
    _show(ctx, "Acts like a normal foreground user and follows the real CLI/Core path.")
    _show(ctx, "Read-only mode: it will not create, edit, start, pause, complete, or remove anything.")
    _show(ctx, "")

    probes: list[DemoProbe] = []
    probe, _ = _probe(
        ctx,
        "Command registry",
        lambda: ctx.commands.names(include_aliases=True),
        detail=_command_registry_detail,
        reproduce="caldav-assistant help all",
    )
    probes.append(probe)

    settings = getattr(ctx, "settings", None)
    probe, _ = _probe(
        ctx,
        "Background / local IPC",
        lambda: settings.list(),
        detail=lambda value: f"service answered; {_count(value)} setting descriptor(s)",
        reproduce="caldav-assistant background status",
    )
    probes.append(probe)
    if probe.status == "FAIL":
        for name, reproduce in (
            ("CalDAV status", "caldav-assistant settings caldav status"),
            ("Task read", "caldav-assistant tasks"),
            ("Event read", "caldav-assistant events"),
            ("Agenda today", "caldav-assistant today"),
            ("Next recommendation", "caldav-assistant next"),
            ("Current work / Session", "caldav-assistant current"),
            ("Activity Journal read", "caldav-assistant history"),
            ("WordPress Outbox read", "caldav-assistant history"),
            ("CalDAV authenticated connection", "caldav-assistant settings caldav test"),
        ):
            probes.append(_skip(ctx, name, "Background / IPC is unavailable", reproduce=reproduce))
        return _finish_report(ctx, probes, setup_missing=False)

    probe, caldav_status = _probe(
        ctx,
        "CalDAV status",
        lambda: _caldav_status(settings),
        detail=_caldav_status_detail,
        reproduce="caldav-assistant settings caldav status",
    )
    probes.append(probe)
    setup_missing = bool(
        probe.status == "PASS"
        and isinstance(caldav_status, dict)
        and not caldav_status.get("base_url_configured")
    )

    if setup_missing:
        for name, reproduce in (
            ("Task read", "caldav-assistant tasks"),
            ("Event read", "caldav-assistant events"),
            ("Agenda today", "caldav-assistant today"),
            ("Next recommendation", "caldav-assistant next"),
        ):
            probes.append(_skip(ctx, name, "CalDAV server is not configured", reproduce=reproduce))
    else:
        probe, _ = _probe(
            ctx,
            "Task read",
            lambda: ctx.tasks.list(),
            detail=lambda value: f"{_count(value)} task(s) returned",
            reproduce="caldav-assistant tasks",
        )
        probes.append(probe)
        probe, _ = _probe(
            ctx,
            "Event read",
            lambda: ctx.events.list(),
            detail=lambda value: f"{_count(value)} event(s) returned",
            reproduce="caldav-assistant events",
        )
        probes.append(probe)
        probe, _ = _probe(
            ctx,
            "Agenda today",
            lambda: ctx.agenda.today(),
            detail=lambda value: f"{_count(getattr(value, 'items', ()) or ())} agenda item(s)",
            reproduce="caldav-assistant today",
        )
        probes.append(probe)
        probe, _ = _probe(
            ctx,
            "Next recommendation",
            lambda: ctx.agenda.next(),
            detail=lambda value: f"recommendation={_summary(getattr(value, 'value', value))}",
            reproduce="caldav-assistant next",
        )
        probes.append(probe)

    probe, _ = _probe(
        ctx,
        "Current work / Session",
        lambda: ctx.session.current_task(),
        detail=lambda value: f"current={_summary(value)}",
        reproduce="caldav-assistant current",
    )
    probes.append(probe)
    probe, _ = _probe(
        ctx,
        "Activity Journal read",
        lambda: ctx.activity.today(),
        detail=lambda value: f"{_count(value)} activity record(s) today",
        reproduce="caldav-assistant history",
    )
    probes.append(probe)
    probe, _ = _probe(
        ctx,
        "WordPress Outbox read",
        lambda: ctx.wordpress.pending(),
        detail=lambda value: f"{_count(value)} pending item(s)",
        reproduce="caldav-assistant history",
    )
    probes.append(probe)

    if setup_missing:
        probes.append(
            _skip(
                ctx,
                "CalDAV authenticated connection",
                "CalDAV server is not configured",
                reproduce="caldav-assistant settings caldav test",
            )
        )
    else:
        action = getattr(settings, "test_caldav_connection", None)
        if callable(action):
            probe, _ = _probe(
                ctx,
                "CalDAV authenticated connection",
                lambda: _connection_test(settings),
                detail=_connection_detail,
                reproduce="caldav-assistant settings caldav test",
            )
            probes.append(probe)
        else:
            probes.append(
                _skip(
                    ctx,
                    "CalDAV authenticated connection",
                    "this client does not expose the CLI connection-test helper",
                    reproduce="caldav-assistant settings caldav test",
                )
            )

    return _finish_report(ctx, probes, setup_missing=setup_missing)


def register_feature_demo_command(commands: Any, ctx: Any) -> None:
    """Register the protected diagnostic action without changing the frozen Public API."""
    if "demo" in set(commands.names(include_aliases=True)):
        return
    commands.register_builtin(
        "demo",
        lambda: run_feature_demo(ctx),
        aliases=("doctor", "diagnose"),
        description="Run a read-only live feature demo and localise slow or failing layers.",
        metadata={"help_category": "system"},
    )


__all__ = ["DemoProbe", "register_feature_demo_command", "run_feature_demo"]
