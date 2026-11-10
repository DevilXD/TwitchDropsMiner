from __future__ import annotations

from types import SimpleNamespace

import pytest

# Twitch.__init__ normally creates a Tk GUI. This test injects a fake GUI, but
# importing twitch still imports gui/pystray; skip where the runtime deps are
# not installed (e.g. a bare global Python used only for the fast tests).
pytest.importorskip("pystray")

from constants import State  # noqa: E402
from twitch import Twitch  # noqa: E402


class FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


class FakeTray:
    def __init__(self) -> None:
        self.icon = ""

    def change_icon(self, icon: str) -> None:
        self.icon = icon


class FakeGUI:
    def __init__(self) -> None:
        self.status = FakeStatus()
        self.tray = FakeTray()
        self.hint = ""

    def set_state_hint(self, hint: str) -> None:
        self.hint = hint


def make_twitch() -> Twitch:
    return Twitch(SimpleNamespace(), gui=FakeGUI())


def test_external_request_is_latched_and_pipeline_yields() -> None:
    twitch = make_twitch()
    twitch.change_state(State.INVENTORY_FETCH)
    twitch.request_state(State.RESTART)

    assert twitch._pending_state is State.RESTART
    assert twitch._advance_state(State.GAMES_UPDATE) is False
    assert twitch.state is State.INVENTORY_FETCH

    twitch._apply_pending_state()
    assert twitch.state is State.RESTART
    assert twitch._pending_state is None


def test_exit_clears_pending_and_is_terminal() -> None:
    twitch = make_twitch()
    twitch.request_state(State.RESTART)
    twitch.request_state(State.EXIT)

    assert twitch.state is State.EXIT
    assert twitch._pending_state is None

    twitch.request_state(State.INVENTORY_FETCH)
    assert twitch.state is State.EXIT


def test_state_snapshot_includes_pending_request() -> None:
    twitch = make_twitch()
    twitch.request_state(State.RULES_UPDATE, reason="settings changed")

    snapshot = twitch.state_snapshot()
    assert snapshot["pending"] == "RULES_UPDATE"
    assert snapshot["pending_reason"] == "settings changed"


def test_restart_is_not_overwritten_by_later_requests() -> None:
    twitch = make_twitch()
    twitch.request_state(State.RESTART)
    twitch.request_state(State.INVENTORY_FETCH)
    assert twitch._pending_state is State.RESTART

    twitch.request_state(State.EXIT)
    assert twitch.state is State.EXIT


def test_restart_replaces_a_less_urgent_pending_request() -> None:
    twitch = make_twitch()
    twitch.request_state(State.INVENTORY_FETCH)
    assert twitch._pending_state is State.INVENTORY_FETCH

    twitch.request_state(State.RESTART)
    assert twitch._pending_state is State.RESTART


def test_deferred_channel_request_does_not_skip_the_pipeline() -> None:
    twitch = make_twitch()
    twitch.change_state(State.CHANNELS_FETCH)
    twitch.request_state(State.CHANNEL_SWITCH)

    # A channel-level request must not cut the inventory pass short.
    twitch._apply_pending_state()
    assert twitch.state is State.CHANNELS_FETCH
    assert twitch._pending_state is State.CHANNEL_SWITCH

    # Once the pipeline reaches the matching step, the request is satisfied.
    twitch.change_state(State.CHANNEL_SWITCH)
    twitch._apply_pending_state()
    assert twitch.state is State.CHANNEL_SWITCH
    assert twitch._pending_state is None


def test_urgent_request_preempts_the_next_pipeline_step() -> None:
    twitch = make_twitch()
    twitch.change_state(State.INVENTORY_FETCH)
    twitch.request_state(State.RULES_UPDATE)

    assert twitch._advance_state(State.GAMES_UPDATE) is False
    assert twitch.state is State.INVENTORY_FETCH

    twitch._apply_pending_state()
    assert twitch.state is State.RULES_UPDATE


def test_same_state_request_keeps_its_reason() -> None:
    twitch = make_twitch()
    twitch.change_state(State.INVENTORY_FETCH)
    twitch.request_state(State.INVENTORY_FETCH, reason="progress stalled")

    twitch._apply_pending_state()

    assert twitch.state is State.INVENTORY_FETCH
    assert twitch._lifecycle.reason == "progress stalled"
