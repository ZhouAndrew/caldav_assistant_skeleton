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


def _live_current_task_id(app: Any) -> str | None:
    """Read only authoritative current-work identity, never the whole startup bundle.

    This is an early UX preflight. The actual ``tasks.start`` Core action still owns
    authorization and re-checks both the target Task and open Work state before any
    mutation. A stale Agenda/Recommendation therefore cannot disable Start merely
    because the home-screen latency budget was exceeded.
    """
    runtime = getattr(app, "runtime", None)
    execute = getattr(runtime, "_execute", None)
    if callable(execute):
        value = execute(
            "session.current_task_id",
            {},
            timeout=latency_guard.STARTUP_READ_TIMEOUT_SECONDS,
        )
    else:
        call = getattr(runtime, "call", None)
        if not callable(call):
            raise RuntimeError("This client has no background Runtime connection")
        value = call("session.current_task_id")

    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


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

            The live read and its heartbeat remain visible immediately. Only the small
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
            """Use a narrow live Work preflight when the menu was built from cache.

            Startup's three-second budget applies to the home-screen bundle, not to
            authorization of a later explicit Start action. Re-reading Tasks, Events,
            recommendation and Work here created a deterministic stale->retry->stale
            loop on machines where the complete bundle takes just over that budget.

            The preflight below only answers whether another Work interval is open.
            The Core Start action remains the authority: it refreshes the selected
            Task by id and reads open Work again before it writes anything.
            """
            if (
                not _guided_start_uses_stale_input(task, options)
                or not _can_live_revalidate(app)
            ):
                return original_guided_start(app, task, **options)

            conversation._show(
                app,
                "Cached data cannot safely confirm current work; checking live current work before Start…",
            )
            try:
                current_id = conversation._visible_call(
                    app,
                    "Checking live current work…",
                    lambda: _live_current_task_id(app),
                )
            except Exception as exc:
                # This check is an early convenience only. Do not turn its latency
                # budget into a second authorization gate: the Core Start action has
                # the mutation-safe authoritative preflight and will fail before any
                # write if live Task/Work truth is unavailable.
                conversation._show(
                    app,
                    "Current-work precheck did not finish in the interactive budget; "
                    "Start itself will verify live Task and Work state before changing anything. "
                    f"{type(exc).__name__}: {exc}",
                )
                current_id = None

            if current_id is not None:
                conversation._show(
                    app,
                    "Live CalDAV reports that a Task is already being worked on.",
                )
                conversation._show(
                    app,
                    "Pause or complete it before starting another Task.",
                )
                return "wait"

            updated = dict(options)
            # A verified empty current-work identity is sufficient for the guided
            # prompt. Keep the cached Task only as a selection/display object; Core
            # refreshes that Task by id before mutation.
            updated["known_current"] = None
            return original_guided_start(app, task, **updated)

        conversation._guided_start = guided_start

    module._stale_startup_notice_installed = True


__all__ = ["install"]
