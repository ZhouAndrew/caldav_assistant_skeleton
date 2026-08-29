"""Bundled Virtual Assistant extension using classic, explainable AI.

This module deliberately imports only the public API. It never mutates Task/Event
facts from reminder rules. CalDAV remains authoritative; the extension only scores,
summarizes and recommends.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from caldav_assistant.api.v1 import Event, NotificationRequest, Task


class ClassicAssistantPolicy:
    """Tiny expert-system policy for proactive Task reminders.

    The policy combines deadline distance and iCalendar priority into a transparent
    score. It emits fixed trigger opportunities, so ReminderService's existing
    delivery-key de-duplication remains authoritative and restart-safe.
    """

    name = "classic-assistant-v1"

    @staticmethod
    def _aware_pair(left: datetime, right: datetime) -> tuple[datetime, datetime] | None:
        if (left.tzinfo is None) != (right.tzinfo is None):
            return None
        return left, right

    @staticmethod
    def score(task: Task, now: datetime) -> tuple[int, tuple[str, ...]]:
        due = task.due
        if not isinstance(due, datetime):
            return 0, ()
        pair = ClassicAssistantPolicy._aware_pair(due, now)
        if pair is None:
            return 0, ()
        due, now = pair
        remaining = (due - now).total_seconds()
        reasons: list[str] = []
        score = 0

        if remaining <= 0:
            score += 70
            reasons.append("overdue")
        elif remaining <= 30 * 60:
            score += 60
            reasons.append("due_within_30m")
        elif remaining <= 2 * 3600:
            score += 45
            reasons.append("due_within_2h")
        elif remaining <= 24 * 3600:
            score += 25
            reasons.append("due_within_24h")

        priority = task.priority
        if isinstance(priority, int):
            if priority <= 3:
                score += 25
                reasons.append("high_priority")
            elif priority <= 5:
                score += 10
                reasons.append("medium_priority")

        if task.status == "IN-PROCESS":
            score += 5
            reasons.append("in_progress")

        return min(100, score), tuple(reasons)

    def evaluate(self, item: Task | Event, now: datetime):
        if not isinstance(item, Task):
            return None
        if item.completed or item.status in {"COMPLETED", "CANCELLED"}:
            return None
        due = item.due
        if not isinstance(due, datetime):
            return None
        if self._aware_pair(due, now) is None:
            return None

        priority = item.priority if isinstance(item.priority, int) else 9
        triggers: list[tuple[str, datetime]] = []

        # High priority receives one earlier planning nudge. Ordinary Tasks start
        # at two hours, then receive a final thirty-minute reminder.
        if priority <= 3:
            triggers.append(("24h", due - timedelta(hours=24)))
        triggers.extend(
            [
                ("2h", due - timedelta(hours=2)),
                ("30m", due - timedelta(minutes=30)),
            ]
        )

        requests: list[NotificationRequest] = []
        for label, when in triggers:
            # Do not manufacture ancient catch-up nudges after the actual deadline;
            # the Core due reminder handles the deadline itself.
            if when < now - timedelta(minutes=5):
                continue
            score, reasons = self.score(item, when)
            body = self._body(item, label, score)
            requests.append(
                NotificationRequest(
                    key=f"assistant:{self.name}:{item.id}:{due.isoformat()}:{label}",
                    when=when,
                    title=f"Upcoming: {item.summary}",
                    body=body,
                    source="virtual_assistant",
                    object_id=item.id,
                    metadata={
                        "assistant": self.name,
                        "score": score,
                        "reasons": list(reasons),
                        "trigger": label,
                        "due": due.isoformat(),
                    },
                )
            )
        return requests

    @staticmethod
    def _body(task: Task, label: str, score: int) -> str:
        labels = {"24h": "about 24 hours", "2h": "about 2 hours", "30m": "about 30 minutes"}
        text = labels.get(label, label)
        if score >= 70:
            advice = "This looks urgent; consider making it your next focus."
        elif score >= 45:
            advice = "It is becoming time-sensitive."
        else:
            advice = "A useful time to plan the remaining work."
        return f"Due in {text}. {advice}"


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def build_summary(ctx: Any, *, now: datetime | None = None) -> str:
    """Build a human-readable progress summary from public Object API facts."""
    moment = now or datetime.now().astimezone()
    today = moment.date()
    tasks = list(ctx.tasks.list())

    completed_today = 0
    active = 0
    overdue = 0
    for task in tasks:
        if not isinstance(task, Task):
            continue
        completed_at = task.completed_at
        if task.completed and isinstance(completed_at, datetime):
            local_completed = completed_at.astimezone() if completed_at.tzinfo else completed_at
            if local_completed.date() == today:
                completed_today += 1
        if not task.completed and task.status != "CANCELLED":
            active += 1
            due = task.due
            if isinstance(due, datetime):
                local_due = due.astimezone(moment.tzinfo) if due.tzinfo and moment.tzinfo else due
                comparable_now = moment if local_due.tzinfo else moment.replace(tzinfo=None)
                if local_due < comparable_now:
                    overdue += 1
            elif isinstance(due, date) and due < today:
                overdue += 1

    lines = [
        "Assistant progress",
        f"Completed today: {completed_today}",
        f"Active tasks: {active}",
        f"Overdue: {overdue}",
    ]

    current = ctx.session.current_task()
    if isinstance(current, Task):
        try:
            seconds = float(ctx.session.work_seconds(current))
        except Exception:
            seconds = 0.0
        lines.extend(
            [
                "",
                f"Current: {current.summary}",
                f"Accumulated active time: {_duration(seconds)}",
            ]
        )

    try:
        paused = list(ctx.session.paused_tasks())
    except Exception:
        paused = []
    if paused:
        lines.append(f"Paused tasks: {len(paused)}")

    return "\n".join(lines)


def install(ctx: Any, *, reminder_rules: Any) -> None:
    """Install this bundled extension into the supplied public application context."""
    reminder_rules.register(ClassicAssistantPolicy(), owner="virtual_assistant")

    def assistant_command():
        text = build_summary(ctx)
        show = getattr(ctx.ui, "show", None)
        if callable(show):
            show(text)
        return text

    try:
        ctx.commands.register_extension(
            "assistant",
            assistant_command,
            extension="virtual_assistant",
            description="Show the built-in virtual assistant progress summary.",
        )
    except Exception:
        # Service and CLI contexts can coexist in tests. A duplicate registration in
        # one process must not disable reminder intelligence in the service context.
        pass


__all__ = ["ClassicAssistantPolicy", "build_summary", "install"]
