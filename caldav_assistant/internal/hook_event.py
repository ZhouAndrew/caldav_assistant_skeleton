# CALDAV_ASSISTANT_HOOK_EVENT_API_V1
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import re
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Mapping
import weakref


_EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def _validate_event_name(name: str) -> str:
    if not isinstance(name, str) or not _EVENT_NAME_RE.fullmatch(name):
        raise ValueError(
            "hook event name must contain at least two dot-separated "
            "ASCII-safe segments, for example 'task.completed'"
        )
    return name


@dataclass(frozen=True, slots=True)
class HookEvent:
    """Immutable event delivered to extension hook handlers."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _validate_event_name(self.name)
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


@dataclass(frozen=True, slots=True)
class HookFailure:
    event_name: str
    handler_name: str
    owner: str
    error: Exception


@dataclass(frozen=True, slots=True)
class HookDispatchReport:
    event: HookEvent
    called: int
    failures: tuple[HookFailure, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class HookHandle:
    id: int
    event_name: str
    owner: str


@dataclass(slots=True)
class _Subscription:
    handle: HookHandle
    priority: int
    once: bool
    order: int
    handler_name: str
    handler_ref: Any

    def resolve(self) -> Callable[[HookEvent], Any] | None:
        return self.handler_ref()


def _make_weak_handler_ref(handler: Callable[[HookEvent], Any]):
    if inspect.ismethod(handler):
        return weakref.WeakMethod(handler)
    try:
        return weakref.ref(handler)
    except TypeError:
        return lambda: handler


class EventBus:
    """Synchronous Full Extension API v1 event bus.

    Higher priority runs first; equal priority keeps registration order. Hook
    failures are isolated and returned in the report. Async handlers are rejected.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscriptions: dict[str, list[_Subscription]] = {}
        self._next_id = 1
        self._next_order = 1

    def subscribe(
        self,
        event_name: str,
        handler: Callable[[HookEvent], Any],
        *,
        priority: int = 0,
        once: bool = False,
        owner: str | None = None,
    ) -> HookHandle:
        event_name = _validate_event_name(event_name)
        if not callable(handler):
            raise TypeError("handler must be callable")
        if inspect.iscoroutinefunction(handler):
            raise TypeError("async hook handlers are not supported by synchronous API v1")
        if not isinstance(priority, int):
            raise TypeError("priority must be an int")
        if not isinstance(once, bool):
            raise TypeError("once must be a bool")

        owner_name = owner or getattr(handler, "__module__", None) or "<unknown>"
        handler_name = getattr(handler, "__qualname__", repr(handler))

        with self._lock:
            bucket = self._subscriptions.setdefault(event_name, [])
            bucket[:] = [
                sub
                for sub in bucket
                if not (
                    sub.handle.owner == owner_name
                    and sub.handler_name == handler_name
                )
            ]
            handle = HookHandle(
                id=self._next_id,
                event_name=event_name,
                owner=owner_name,
            )
            self._next_id += 1
            bucket.append(
                _Subscription(
                    handle=handle,
                    priority=priority,
                    once=once,
                    order=self._next_order,
                    handler_name=handler_name,
                    handler_ref=_make_weak_handler_ref(handler),
                )
            )
            self._next_order += 1
            bucket.sort(key=lambda sub: (-sub.priority, sub.order))
            return handle

    def unsubscribe(self, handle: HookHandle) -> bool:
        if not isinstance(handle, HookHandle):
            raise TypeError("handle must be HookHandle")
        with self._lock:
            bucket = self._subscriptions.get(handle.event_name)
            if not bucket:
                return False
            before = len(bucket)
            bucket[:] = [sub for sub in bucket if sub.handle.id != handle.id]
            if not bucket:
                self._subscriptions.pop(handle.event_name, None)
            return len(bucket) != before

    def unregister_owner(self, owner: str) -> int:
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a non-empty string")
        removed = 0
        with self._lock:
            for event_name in list(self._subscriptions):
                bucket = self._subscriptions[event_name]
                before = len(bucket)
                bucket[:] = [sub for sub in bucket if sub.handle.owner != owner]
                removed += before - len(bucket)
                if not bucket:
                    self._subscriptions.pop(event_name, None)
        return removed

    def prune(self) -> int:
        """Remove dead weak-reference handlers left by unloaded modules."""
        removed = 0
        with self._lock:
            for event_name in list(self._subscriptions):
                bucket = self._subscriptions[event_name]
                before = len(bucket)
                bucket[:] = [sub for sub in bucket if sub.resolve() is not None]
                removed += before - len(bucket)
                if not bucket:
                    self._subscriptions.pop(event_name, None)
        return removed

    def listeners(self, event_name: str | None = None) -> int:
        self.prune()
        with self._lock:
            if event_name is None:
                return sum(len(bucket) for bucket in self._subscriptions.values())
            clean = _validate_event_name(event_name)
            return len(self._subscriptions.get(clean, ()))

    def emit(
        self,
        event_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
        source: str | None = None,
        **values: Any,
    ) -> HookDispatchReport:
        clean = _validate_event_name(event_name)
        combined = dict(payload or {})
        combined.update(values)
        hook_event = HookEvent(clean, combined, source=source)
        with self._lock:
            subscriptions = tuple(self._subscriptions.get(clean, ()))

        called = 0
        failures: list[HookFailure] = []
        for sub in subscriptions:
            handler = sub.resolve()
            if handler is None:
                self.unsubscribe(sub.handle)
                continue
            if sub.once:
                self.unsubscribe(sub.handle)
            try:
                handler(hook_event)
                called += 1
            except Exception as exc:
                called += 1
                failures.append(
                    HookFailure(
                        event_name=hook_event.name,
                        handler_name=sub.handler_name,
                        owner=sub.handle.owner,
                        error=exc,
                    )
                )

        self.prune()
        return HookDispatchReport(
            event=hook_event,
            called=called,
            failures=tuple(failures),
        )


_default_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _default_event_bus


def on(
    event_name: str,
    *,
    priority: int = 0,
    once: bool = False,
    owner: str | None = None,
    bus: EventBus | None = None,
):
    target_bus = bus or _default_event_bus

    def decorator(handler: Callable[[HookEvent], Any]):
        handle = target_bus.subscribe(
            event_name,
            handler,
            priority=priority,
            once=once,
            owner=owner,
        )
        setattr(handler, "__caldav_hook_handle__", handle)
        setattr(handler, "__caldav_hook_event__", event_name)
        return handler

    return decorator


def emit(
    event_name: str,
    *,
    payload: Mapping[str, Any] | None = None,
    source: str | None = None,
    **values: Any,
) -> HookDispatchReport:
    return _default_event_bus.emit(
        event_name,
        payload=payload,
        source=source,
        **values,
    )


def off(handle: HookHandle) -> bool:
    return _default_event_bus.unsubscribe(handle)


def unregister_owner(owner: str) -> int:
    return _default_event_bus.unregister_owner(owner)

__all__ = [
    "HookEvent",
    "HookFailure",
    "HookDispatchReport",
    "HookHandle",
    "EventBus",
    "get_event_bus",
    "on",
    "emit",
    "off",
    "unregister_owner",
]
