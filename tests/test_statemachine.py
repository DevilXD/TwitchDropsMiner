from __future__ import annotations

import json
from enum import Enum, auto

import pytest

from constants import State
from lifecycle import (
    DEFERRED_REQUESTS,
    MINER_TRANSITIONS,
    PIPELINE_TRANSITIONS,
    REQUESTABLE_STATES,
    SETTLED_STATES,
    STATE_STATUS,
    STATE_TRAY_ICON,
    URGENT_REQUESTS,
    create_miner_statemachine,
)
from statemachine import InvalidTransition, StateMachine


class Demo(Enum):
    A = auto()
    B = auto()
    C = auto()


TABLE = {
    Demo.A: {Demo.B},
    Demo.B: {Demo.C},
    Demo.C: set(),
}


def test_initial_state() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    assert machine.state is Demo.A
    assert machine.reason == ""
    assert machine.history == ()


def test_legal_transition_is_recorded_with_reason() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    assert machine.set(Demo.B, reason="go") is True
    assert machine.state is Demo.B
    assert machine.reason == "go"
    assert len(machine.history) == 1
    transition = machine.history[0]
    assert transition.source is Demo.A
    assert transition.target is Demo.B
    assert transition.reason == "go"


def test_illegal_transition_raises_in_strict_mode() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    with pytest.raises(InvalidTransition):
        machine.set(Demo.C)
    assert machine.state is Demo.A


def test_illegal_transition_is_applied_in_non_strict_mode() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A, strict=False)
    assert machine.set(Demo.C) is True
    assert machine.state is Demo.C


def test_same_state_without_reason_is_a_noop() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    assert machine.set(Demo.A) is False
    assert machine.history == ()


def test_same_state_with_reason_is_recorded() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    assert machine.set(Demo.A, reason="refreshed") is True
    assert machine.reason == "refreshed"
    transition = machine.history[-1]
    assert transition.source is Demo.A
    assert transition.target is Demo.A


def test_listeners_observe_changes() -> None:
    seen = []
    listener = seen.append
    machine = StateMachine(Demo, TABLE, initial=Demo.A, on_change=listener)
    machine.set(Demo.B)
    assert [transition.target for transition in seen] == [Demo.B]
    machine.remove_listener(listener)
    machine.set(Demo.C)
    assert [transition.target for transition in seen] == [Demo.B]


def test_force_and_reset() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    machine.force(Demo.C, reason="recover")
    assert machine.state is Demo.C
    assert machine.reason == "recover"
    machine.reset(reason="restart")
    assert machine.state is Demo.A
    assert machine.reason == "restart"


def test_as_dict_is_json_serializable() -> None:
    machine = StateMachine(Demo, TABLE, initial=Demo.A)
    machine.set(Demo.B, reason="reason")
    snapshot = machine.as_dict()
    assert snapshot["state"] == "B"
    assert snapshot["allowed"] == ["C"]
    assert snapshot["history"][0]["from"] == "A"
    assert snapshot["history"][0]["to"] == "B"
    json.dumps(snapshot)


def test_table_must_describe_every_state() -> None:
    with pytest.raises(ValueError, match="missing transition entries"):
        StateMachine(Demo, {Demo.A: {Demo.B}}, initial=Demo.A)


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown target state"):
        StateMachine(
            Demo,
            {Demo.A: {Demo.B}, Demo.B: {object()}, Demo.C: set()},  # type: ignore[dict-item]
            initial=Demo.A,
        )


def test_unknown_initial_state_is_rejected() -> None:
    with pytest.raises(TypeError):
        StateMachine(Demo, TABLE, initial="A")  # type: ignore[arg-type]


def test_miner_table_explicitly_covers_every_state() -> None:
    assert set(MINER_TRANSITIONS) == set(State)
    assert set(PIPELINE_TRANSITIONS) == set(State)
    assert set(STATE_STATUS) == set(State)
    assert set(STATE_TRAY_ICON) == set(State)


def test_requestable_states_partition_into_urgent_and_deferred() -> None:
    assert URGENT_REQUESTS.isdisjoint(DEFERRED_REQUESTS)
    assert URGENT_REQUESTS | DEFERRED_REQUESTS | {State.EXIT} == REQUESTABLE_STATES
    assert SETTLED_STATES <= set(State)


def test_miner_exit_is_terminal() -> None:
    assert MINER_TRANSITIONS[State.EXIT] == frozenset()


def test_miner_external_requests_are_reachable_from_every_live_state() -> None:
    for state in State:
        if state is State.EXIT:
            continue
        for request in REQUESTABLE_STATES:
            assert request in MINER_TRANSITIONS[state], f"{state.name} cannot request {request.name}"


def test_miner_pipeline_edges_are_declared() -> None:
    assert State.GAMES_UPDATE in MINER_TRANSITIONS[State.INVENTORY_FETCH]
    assert State.CHANNELS_CLEANUP in MINER_TRANSITIONS[State.GAMES_UPDATE]
    assert State.CHANNELS_FETCH in MINER_TRANSITIONS[State.CHANNELS_CLEANUP]
    assert State.IDLE in MINER_TRANSITIONS[State.CHANNELS_CLEANUP]
    assert State.CHANNEL_SWITCH in MINER_TRANSITIONS[State.CHANNELS_FETCH]
    assert State.IDLE in MINER_TRANSITIONS[State.CHANNEL_SWITCH]


def test_miner_state_status_translations_exist() -> None:
    from translate import _

    for path in STATE_STATUS.values():
        value = _(*path)
        assert isinstance(value, str) and value


def test_miner_strict_mode_accepts_every_real_flow() -> None:
    machine = create_miner_statemachine(strict=True)
    # Happy path, one full pass.
    for state in (
        State.INVENTORY_FETCH,
        State.GAMES_UPDATE,
        State.CHANNELS_CLEANUP,
        State.CHANNELS_FETCH,
        State.CHANNEL_SWITCH,
        State.IDLE,
    ):
        machine.set(state)
    # Local settings changes take the short path through GAMES_UPDATE.
    machine.set(State.RULES_UPDATE)
    machine.set(State.GAMES_UPDATE)
    machine.set(State.CHANNELS_CLEANUP)
    machine.set(State.CHANNELS_FETCH)
    machine.set(State.CHANNEL_SWITCH)
    machine.set(State.IDLE)
    # External requests can interrupt from any live state.
    for state in (
        State.CHANNEL_SWITCH,
        State.INVENTORY_FETCH,
        State.CHANNEL_SWITCH,
        State.RESTART,
        State.EXIT,
    ):
        machine.set(state)
    assert machine.state is State.EXIT
