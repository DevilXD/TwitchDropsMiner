from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Mapping, TypeVar

S = TypeVar("S", bound=Enum)

logger = logging.getLogger("TwitchDrops.statemachine")


class InvalidTransition(RuntimeError):
    """
    Raised when a state machine is asked to perform an illegal transition
    while running in strict mode.
    """


@dataclass(frozen=True)
class Transition(Generic[S]):
    """
    A single, immutable record of a state change.
    """

    source: S
    target: S
    reason: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        reason = f" ({self.reason})" if self.reason else ""
        return f"{self.source.name} -> {self.target.name}{reason}"


class StateMachine(Generic[S]):
    """
    A small, explicit finite state machine.

    The point of this class is to make state that already exists in the application
    *readable*: every state has a name, every allowed transition is declared up front,
    every change carries a reason and a timestamp, and listeners can observe changes.

    It intentionally has no async or application dependencies, so it can be used from
    the GUI, the miner, and from tests without booting any of them.

    Notes:
    ------
    * `transitions` must contain an entry for *every* state, even if that entry is
      an empty set. This makes the machine self-documenting and makes forgetting
      to describe a state a hard error, instead of a runtime surprise.
    * Self-transitions are always allowed and are recorded, which is useful for
      "re-requested" events. A same-state request without a reason is treated as a
      no-op and returns False.
    * In non-strict mode an illegal transition is logged and applied. This keeps
      the machine usable as an observability layer while existing code is migrated.
    """

    def __init__(
        self,
        states: type[S],
        transitions: Mapping[S, Iterable[S]],
        *,
        initial: S,
        name: str = "state machine",
        strict: bool = True,
        history: int = 32,
        on_change: Callable[[Transition[S]], None] | None = None,
    ) -> None:
        if not isinstance(initial, states):
            raise TypeError(f"{name}: initial state must be a {states.__name__} member")
        known = set(states)
        table: dict[S, frozenset[S]] = {}
        for source, targets in transitions.items():
            if not isinstance(source, states):
                raise ValueError(f"{name}: unknown source state: {source!r}")
            target_set = frozenset(targets)
            unknown = target_set - known
            if unknown:
                names = ", ".join(
                    sorted(getattr(state, "name", repr(state)) for state in unknown)
                )
                raise ValueError(f"{name}: unknown target state(s) for {source.name}: {names}")
            table[source] = target_set
        missing = known - table.keys()
        if missing:
            names = ", ".join(sorted(state.name for state in missing))
            raise ValueError(f"{name}: missing transition entries for: {names}")
        self._states = states
        self._table = table
        self._initial = initial
        self._state = initial
        self._reason = ""
        self._changed_at = datetime.now(timezone.utc)
        self._history: deque[Transition[S]] = deque(maxlen=history)
        self._listeners: list[Callable[[Transition[S]], None]] = []
        self.name = name
        self.strict = strict
        if on_change is not None:
            self._listeners.append(on_change)

    def __repr__(self) -> str:
        reason = f", reason={self._reason!r}" if self._reason else ""
        return f"{self.__class__.__name__}({self.name}: {self._state.name}{reason})"

    @property
    def states(self) -> type[S]:
        return self._states

    @property
    def state(self) -> S:
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def changed_at(self) -> datetime:
        return self._changed_at

    @property
    def history(self) -> tuple[Transition[S], ...]:
        return tuple(self._history)

    @property
    def transitions(self) -> Mapping[S, frozenset[S]]:
        return MappingProxyType(self._table)

    def allowed(self) -> frozenset[S]:
        """Return every state reachable from the current state."""
        return self._table[self._state]

    def can(self, target: S) -> bool:
        return target is self._state or target in self._table[self._state]

    def is_(self, state: S) -> bool:
        return self._state is state

    def on_change(self, listener: Callable[[Transition[S]], None]) -> None:
        """Register a listener called after every successfully applied change."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[Transition[S]], None]) -> None:
        self._listeners.remove(listener)

    def set(self, target: S, *, reason: str = "") -> bool:
        """
        Apply a transition to `target`.

        Returns True when the machine changed (or recorded a reasoned self-transition),
        False when the request was a no-op.
        """
        if not isinstance(target, self._states):
            raise TypeError(f"{self.name}: target must be a {self._states.__name__} member")
        if target is self._state and not reason:
            return False
        if target is not self._state and target not in self._table[self._state]:
            message = (
                f"{self.name}: illegal transition {self._state.name} -> {target.name}"
            )
            if self.strict:
                raise InvalidTransition(message)
            logger.warning(message)
        transition = Transition(self._state, target, reason)
        self._state = target
        self._reason = reason
        self._changed_at = transition.at
        self._history.append(transition)
        for listener in tuple(self._listeners):
            listener(transition)
        return True

    def force(self, target: S, *, reason: str = "") -> None:
        """
        Apply a transition without validating it.

        Intended for explicit resets and recovery paths. The change is still
        recorded in the history, so it remains visible to observers.
        """
        if not isinstance(target, self._states):
            raise TypeError(f"{self.name}: target must be a {self._states.__name__} member")
        transition = Transition(self._state, target, reason)
        self._state = target
        self._reason = reason
        self._changed_at = transition.at
        self._history.append(transition)
        for listener in tuple(self._listeners):
            listener(transition)

    def reset(self, *, reason: str = "") -> None:
        """Force the machine back to its initial state."""
        self.force(self._initial, reason=reason)

    def as_dict(self) -> dict[str, object]:
        """
        Return a JSON-serializable snapshot of the machine.

        This is the agent-facing view: it answers "where am I, what can I do next,
        how did I get here, and why" without reading the implementation.
        """
        return {
            "name": self.name,
            "state": self._state.name,
            "reason": self._reason,
            "changed_at": self._changed_at.isoformat(),
            "allowed": sorted(state.name for state in self.allowed()),
            "history": [
                {
                    "from": transition.source.name,
                    "to": transition.target.name,
                    "reason": transition.reason,
                    "at": transition.at.isoformat(),
                }
                for transition in self._history
            ],
        }
