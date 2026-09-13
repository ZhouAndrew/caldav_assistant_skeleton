"""Keep stale startup data useful without turning it into current-work truth."""
from __future__ import annotations

from typing import Any

from . import latency_guard


_NOTICE = (
    "Warning: Cached Task/Event data — the live read missed the interactive "
    "deadline; this may be out of date."
)
_UNVERIFIED_CURRENT = (
    "  Current work could not be verified live; cached Task/Event data cannot prove "
    "that no Task is active."
)


def _value_is_stale(value: Any) -> bool:
    return value is not None and bool(getattr(value, "stale", False))


def _snapshot_is_stale(snapshot: Any) -> bool:
    if bool(getattr(snapshot, "stale", False)):
        return True
    values = [
        getattr(snapshot, "current_task", None),
        getattr(snapshot, "recommended", None),
        *(getattr(snapshot, "tasks", ()) or ()),
    ]
    values.extend(
        getattr(item, "value", None)
        for item in (getattr(snapshot, "upcoming", ()) or ())
    )
    return any(_value_is_stale(value) for value in values)


def _guided_start_uses_stale_input(task: Any, options: dict[str, Any]) -> bool:
    if _value_is_stale(task) or _value_is_stale(options.get("known_current")):
        return True
    return any(
        _value_is_stale(value)
        for value in (options.get("task_choices") or ())
    )


def _can_live_revalidate(app: Any) -> bool:
    """Only the installed Runtime-backed client can perform this safety refresh."""
    runtime = getattr(app, "runtime", None)
    return callable(getattr(runtime, "call", None)) or callable(
        getattr(runtime, "_execute", None)
    )


def _fresh_equivalent(task: Any, tasks: Any) -> Any:
    if task is None:
        return None
    wanted = str(getattr(task, "id", "") or "").strip()
    if not wanted:
        return None
    for candidate in tasks or ():
        if str(getattr(candidate, "id", "") or "").strip() == wanted:
            return candidate
    return None


def install(module: Any) -> None:
    if bool(getattr(module, "_stale_startup_notice_installed", False)):
        return

    conversation = module.conversation
    original_snapshot_text = conversation._snapshot_text
    original_show_welcome = getattr(conversation, "_show_welcome", None)
    original_guided_start = getattr(conversation, "_guided_start", None)

    def snapshot_text(snapshot: Any) -> str:
        body = original_snapshot_text(snapshot)
        if not _snapshot_is_stale(snapshot):
            return body
        return f"{_NOTICE}\n{body}"

    conversation._snapshot_text = snapshot_text

    if callable(original_show_welcome):
        def show_welcome(app: Any):
            """Never translate an unverified stale Work fact into the word 'No'.

            The live read and its heartbeat remain visible immediately.  Only the small
            finished home-screen block beginning at ``Now`` is held until the returned
            snapshot tells us whether it is stale, then replayed in the same order.
            """
            original_show = conversation._show
            buffered: list[Any] = []
            buffering = False

            def capture(current_app: Any, value: Any = "") -> None:
                nonlocal buffering
                if str(value) == "Now":
                    buffering = True
                if buffering:
                    buffered.append(value)
                else:
                    original_show(current_app, value)

            conversation._show = capture
            try:
                snapshot = original_show_welcome(app)
            finally:
                conversation._show = original_show

            stale = _snapshot_is_stale(snapshot)
            for value in buffered:
                text = str(value)
                if stale and text == "  No Task is currently being worked on.":
                    value = _UNVERIFIED_CURRENT
                elif stale and text.startswith("  ▶ "):
                    value = f"{text}  [cached; live current-work state unverified]"
                original_show(app, value)
            return snapshot

        conversation._show_welcome = show_welcome

    if callable(original_guided_start):
        def guided_start(app: Any, task: Any = None, **options: Any):
            """A stale menu may propose a Task, but it may not authorize ``start``.

            Work VEVENT state is not part of the Task/Event cache.  Before asking the
            human for a duration or confirmation, refresh the same bounded live startup
            bundle.  If live current-work truth is still unavailable, fail closed without
            changing Task state instead of discovering the conflict deep inside a slow
            mutation path.
            """
            if (
                not _guided_start_uses_stale_input(task, options)
                or not _can_live_revalidate(app)
            ):
                return original_guided_start(app, task, **options)

            conversation._show(
                app,
                "Cached data cannot safely confirm current work; verifying live CalDAV before Start…",
            )
            try:
                refreshed = conversation._visible_call(
                    app,
                    "Verifying current work, Tasks and Events…",
                    lambda: latency_guard._read_snapshot(module, app),
                )
            except Exception as exc:
                conversation._show(
                    app,
                    "Current work is still unavailable. Start was not attempted and no Task state changed. "
                    f"{type(exc).__name__}: {exc}",
                )
                return "console"

            if getattr(refreshed, "warning", None) or _snapshot_is_stale(refreshed):
                conversation._show(
                    app,
                    "Live current-work state is still unverified. Start was not attempted and no Task state changed.",
                )
                return "console"

            fresh_tasks = tuple(getattr(refreshed, "tasks", ()) or ())
            fresh_task = _fresh_equivalent(task, fresh_tasks) if task is not None else None
            if task is not None and fresh_task is None:
                conversation._show(
                    app,
                    "That cached Task is no longer available in the verified live snapshot. Start was not attempted.",
                )
                return "console"

            updated = dict(options)
            updated["known_current"] = getattr(refreshed, "current_task", None)
            updated["task_choices"] = fresh_tasks
            return original_guided_start(app, fresh_task, **updated)

        conversation._guided_start = guided_start

    module._stale_startup_notice_installed = True


__all__ = ["install"]
