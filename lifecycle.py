from __future__ import annotations

from typing import Final

from constants import State
from statemachine import StateMachine

# States that any part of the application may request at any moment. These are
# *events*, not pipeline steps: the main loop will pick the latest one up on its
# next iteration. Keeping them in one place is what makes the miner lifecycle
# comprehensible without reading the whole of `Twitch._run`.
REQUESTABLE_STATES: Final[frozenset[State]] = frozenset({
    State.INVENTORY_FETCH,
    State.CHANNEL_SWITCH,
    State.CHANNELS_CLEANUP,
    State.RULES_UPDATE,
    State.RESTART,
    State.EXIT,
})

# Requests that must preempt an in-flight pipeline pass. A reload, a local rules
# change, or a restart changes the inputs of the next pass, so finishing the old
# pass first would either waste work or act on stale settings.
URGENT_REQUESTS: Final[frozenset[State]] = frozenset({
    State.INVENTORY_FETCH,
    State.RULES_UPDATE,
    State.RESTART,
})

# Channel-level requests. They are valid at any time, but must not cut an
# inventory pass short: INVENTORY_FETCH -> GAMES_UPDATE -> CHANNELS_CLEANUP ->
# CHANNELS_FETCH already performs the work they ask for. They are applied once
# the pipeline reaches a settled state.
DEFERRED_REQUESTS: Final[frozenset[State]] = frozenset({
    State.CHANNEL_SWITCH,
    State.CHANNELS_CLEANUP,
})

# Stable states: the pipeline is not mid-pass here, so any deferred request can
# be applied immediately.
SETTLED_STATES: Final[frozenset[State]] = frozenset({
    State.IDLE,
    State.CHANNEL_SWITCH,
})

# Transitions that the main loop performs on its own when a step finishes.
# This is the "happy path" pipeline. Everything else must be requested through
# `REQUESTABLE_STATES`.
PIPELINE_TRANSITIONS: Final[dict[State, frozenset[State]]] = {
    State.IDLE: frozenset(),
    State.INVENTORY_FETCH: frozenset({State.GAMES_UPDATE}),
    State.GAMES_UPDATE: frozenset({State.CHANNELS_CLEANUP}),
    State.CHANNELS_CLEANUP: frozenset({State.CHANNELS_FETCH, State.IDLE}),
    State.CHANNELS_FETCH: frozenset({State.CHANNEL_SWITCH}),
    State.CHANNEL_SWITCH: frozenset({State.IDLE}),
    State.RULES_UPDATE: frozenset({State.GAMES_UPDATE}),
    State.RESTART: frozenset(),
    State.EXIT: frozenset(),
}


def _build_transitions() -> dict[State, frozenset[State]]:
    table: dict[State, frozenset[State]] = {}
    for state in State:
        if state is State.EXIT:
            # EXIT is terminal. `Twitch.change_state` enforces this before the
            # machine is consulted, but it is also encoded here for readers.
            table[state] = frozenset()
        else:
            table[state] = frozenset(
                PIPELINE_TRANSITIONS[state] | REQUESTABLE_STATES
            )
    return table


MINER_TRANSITIONS: Final[dict[State, frozenset[State]]] = _build_transitions()

# What the user sees while the miner is in a given state.
# Values are `translate._()` key paths.
STATE_STATUS: Final[dict[State, tuple[str, ...]]] = {
    State.IDLE: ("gui", "status", "idle"),
    State.INVENTORY_FETCH: ("gui", "status", "fetching_inventory"),
    State.GAMES_UPDATE: ("gui", "status", "games_update"),
    State.CHANNELS_CLEANUP: ("gui", "status", "cleanup"),
    State.CHANNELS_FETCH: ("gui", "status", "gathering"),
    State.CHANNEL_SWITCH: ("gui", "status", "switching"),
    State.RULES_UPDATE: ("gui", "status", "applying_settings"),
    State.RESTART: ("gui", "status", "restarting"),
    State.EXIT: ("gui", "status", "exiting"),
}

# Which tray icon represents a state. `None` means "leave the current icon alone".
# CHANNEL_SWITCH deliberately does not change the icon: the watch method changes
# it to `active` as soon as a channel is selected, and changing it here would
# cause a visible flicker on every switch.
STATE_TRAY_ICON: Final[dict[State, str | None]] = {
    State.IDLE: "idle",
    State.INVENTORY_FETCH: "maint",
    State.GAMES_UPDATE: "maint",
    State.CHANNELS_CLEANUP: "maint",
    State.CHANNELS_FETCH: "maint",
    State.CHANNEL_SWITCH: None,
    State.RULES_UPDATE: "maint",
    State.RESTART: "maint",
    State.EXIT: "pickaxe",
}


def create_miner_statemachine(*, name: str = "miner", strict: bool = False) -> StateMachine[State]:
    """
    Create the miner lifecycle state machine.

    `strict` defaults to False on purpose: transitioning is an observability
    improvement, not a reason to stop a user's mining session if an unanticipated
    external request arrives. In tests (and in development) strict mode can be
    enabled to catch table drift.
    """
    return StateMachine(
        State,
        MINER_TRANSITIONS,
        initial=State.IDLE,
        name=name,
        strict=strict,
        history=64,
    )
