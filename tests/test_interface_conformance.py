"""Verify WebUIManager exposes the same interface as the tkinter GUIManager.

The contract is built by combining two sources:
1. AST parsing of gui.py extracts the full interface of GUIManager and its
   widget classes (StatusBar, ChannelList, LoginForm, etc.)
2. Source scanning of the backend files (twitch.py, inventory.py, etc.) finds
   which methods are actually called at runtime.

A method must exist on the adapter if EITHER:
  - The backend code actually calls it (detected by source scanning), OR
  - It's a public method on a widget class AND the backend code accesses
    that widget object (e.g. self.gui.login means all LoginForm methods
    that are also called somewhere must be implemented)

This catches cases where a method is called through a local variable alias
(e.g. ``login_form = self._twitch.gui.login`` then ``login_form.ask_enter_code()``)
that the regex-only scanner would miss.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_webui_manager_cls = None


def _import_webui_manager():
    global _webui_manager_cls
    if _webui_manager_cls is not None:
        return _webui_manager_cls
    from webui.manager import WebUIManager

    _webui_manager_cls = WebUIManager
    return WebUIManager


def _make_mock_twitch():
    twitch = MagicMock()
    twitch.settings.dark_mode = False
    twitch.settings.tray_notifications = False
    twitch.settings.stdlog = False
    twitch.settings.language = "en"
    twitch.state_change = MagicMock(return_value=MagicMock())
    twitch._session = None
    return twitch


# ---------------------------------------------------------------------------
# Source 1: AST parse gui.py → full widget class interfaces
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUI_SOURCE = (PROJECT_ROOT / "gui.py").read_text(encoding="utf-8")
GUI_TREE = ast.parse(GUI_SOURCE)
_GUI_CLASSES = {node.name: node for node in ast.walk(GUI_TREE) if isinstance(node, ast.ClassDef)}


def _public_members(cls_node: ast.ClassDef) -> tuple[list[str], list[str]]:
    methods, props = [], []
    for item in cls_node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = item.name
        if name.startswith("_"):
            continue
        is_prop = any(
            isinstance(d, ast.Name) and d.id == "property"
            for d in item.decorator_list
        )
        (props if is_prop else methods).append(name)
    return methods, props


def _gui_manager_attr_to_class() -> dict[str, str]:
    """Map GUIManager attribute names to their widget class names."""
    gman = _GUI_CLASSES["GUIManager"]
    init = next(n for n in gman.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    result = {}
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)):
                attr_name = target.attr
                if not attr_name.startswith("_"):
                    result[attr_name] = node.value.func.id
    return result


def _gui_manager_top_members() -> tuple[set[str], set[str]]:
    """Return (methods, properties) on GUIManager itself."""
    gman = _GUI_CLASSES["GUIManager"]
    methods, props = _public_members(gman)
    return set(methods), set(props)


# ---------------------------------------------------------------------------
# Source 2: Source scan backend files → which .gui.* calls are actually made
# ---------------------------------------------------------------------------

EXCLUDED_DIRS = {"webui", "tests", "env", "__pycache__", ".git", ".vscode", ".claude"}
EXCLUDED_FILES = {"main_webui.py"}

_DEEP_RE = re.compile(r"\b\w+\.gui\.(\w+)\.(\w+)")
_SHALLOW_RE = re.compile(r"\b\w+\.gui\.(\w+)\b")

# Known alias patterns where a local variable holds a gui sub-object:
#   login_form = self._twitch.gui.login  →  login_form.ask_enter_code(...)
#   _gui_channels = twitch.gui.channels   →  _gui_channels.display(...)
#   _ws_gui = self._twitch.gui.websockets →  _ws_gui.update(...)
# We hard-code these rather than trying to auto-detect assignments, because
# regex-based alias tracking is extremely fragile (State.INVENTORY_FETCH, etc.
# produce false matches).
_ALIAS_MAP: dict[str, str] = {
    "login_form": "login",
    "_gui_channels": "channels",
    "_ws_gui": "websockets",
}


def _scan_calls() -> dict[str, set[str]]:
    """Scan backend source for .gui.* call sites, including known aliases."""
    subobj_members: dict[str, set[str]] = {}
    shallow_names: set[str] = set()

    for py_file in PROJECT_ROOT.rglob("*.py"):
        rel = py_file.relative_to(PROJECT_ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.name in EXCLUDED_FILES:
            continue
        source = py_file.read_text(encoding="utf-8", errors="replace")

        for m in _DEEP_RE.finditer(source):
            subobj_members.setdefault(m.group(1), set()).add(m.group(2))
        for m in _SHALLOW_RE.finditer(source):
            shallow_names.add(m.group(1))

    # Resolve known aliases: login_form.ask_enter_code → gui.login.ask_enter_code
    _ALIAS_CALL_RE = re.compile(r"(\w+)\.(\w+)\s*\(")
    for py_file in PROJECT_ROOT.rglob("*.py"):
        rel = py_file.relative_to(PROJECT_ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.name in EXCLUDED_FILES:
            continue
        source = py_file.read_text(encoding="utf-8", errors="replace")
        for m in _ALIAS_CALL_RE.finditer(source):
            var, method = m.group(1), m.group(2)
            if var in _ALIAS_MAP:
                gui_attr = _ALIAS_MAP[var]
                subobj_members.setdefault(gui_attr, set()).add(method)

    sub_objects = set(subobj_members.keys())
    top_level = shallow_names - sub_objects

    calls: dict[str, set[str]] = {}
    if top_level:
        calls[""] = top_level
    calls.update(subobj_members)
    return calls


# ---------------------------------------------------------------------------
# Build the combined contract
# ---------------------------------------------------------------------------
# For sub-objects (tray, status, channels, etc.): require every public method
# from the tkinter widget class IF it's also called somewhere in the backend.
# This means:
#   - Methods the backend actually calls are always required (from scan)
#   - Widget methods that are never called are NOT required (intentional omissions)
#   - But if you add a new call to a widget method, the test will catch it
#
# For the manager level (""): require every public method/property from
# GUIManager that the backend actually calls, plus any that the scan finds.

_CALL_SITES = _scan_calls()
_ATTR_TO_CLASS = _gui_manager_attr_to_class()
_MGR_METHODS, _MGR_PROPS = _gui_manager_top_members()

# tkinter-only methods that have no webui equivalent and are never called
# from the backend (twitch.py etc.).  Excluding them avoids false failures.
_MGR_EXCLUDE = {"unfocus", "wnd_proc"}


def _build_contract() -> dict[str, set[str]]:
    contract: dict[str, set[str]] = {}

    # Manager level: require methods/props that are either called by the backend
    # OR exist on GUIManager (since twitch.py could call any of them),
    # minus tkinter-only methods that are never called from the backend.
    mgr_from_ast = (_MGR_METHODS | _MGR_PROPS) - _MGR_EXCLUDE
    mgr_from_scan = _CALL_SITES.get("", set())
    contract[""] = mgr_from_scan | mgr_from_ast

    # Sub-objects: require methods that are actually called from the backend
    # (via direct X.gui.subobj.method() or alias X.gui.subobj then var.method()).
    # Also include sub-objects that are referenced (X.gui.login) even if no
    # method calls on them were found through the alias tracker — in that case
    # we still verify the attribute exists, just with an empty member set.
    for attr, cls_name in _ATTR_TO_CLASS.items():
        scan_members = _CALL_SITES.get(attr, set())
        # If the backend references the sub-object but we found no deep calls,
        # still include it (with whatever members the scan found, even if empty).
        if scan_members or attr in _CALL_SITES.get("", set()):
            contract[attr] = scan_members

    return contract


CONTRACT = _build_contract()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def webui_manager():
    WebUIManager = _import_webui_manager()
    twitch = _make_mock_twitch()
    manager = WebUIManager(twitch)
    yield manager
    try:
        from nicegui import app

        app.routes.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInterfaceConformance:
    """Every attribute and method the codebase calls on .gui must exist on WebUIManager."""

    def test_manager_attributes_exist(self, webui_manager):
        missing = []
        for path, members in CONTRACT.items():
            if path == "":
                obj = webui_manager
            else:
                obj = webui_manager
                for part in path.split("."):
                    if not hasattr(obj, part):
                        missing.append(path)
                        break
                    obj = getattr(obj, part)

            if path in missing:
                continue

            for member in members:
                if not hasattr(obj, member):
                    missing.append(f"{path}.{member}" if path else member)

        if missing:
            pytest.fail(
                "Missing from WebUIManager: " + ", ".join(sorted(missing)),
                pytrace=False,
            )

    @pytest.mark.parametrize(
        "path",
        [p for p in CONTRACT if p != ""],
    )
    def test_sub_object_exists(self, webui_manager, path):
        obj = webui_manager
        for part in path.split("."):
            obj = getattr(obj, part)
        assert obj is not None

    @pytest.mark.parametrize(
        "contract_path,member",
        [
            pytest.param(path, member, id=f"{path}.{member}" if path else member)
            for path, members in CONTRACT.items()
            for member in members
        ],
    )
    def test_each_member_exists(self, webui_manager, contract_path, member):
        if contract_path == "":
            obj = webui_manager
        else:
            obj = webui_manager
            for part in contract_path.split("."):
                obj = getattr(obj, part)

        assert hasattr(obj, member), pytest.fail(
            f"{contract_path}.{member if contract_path else member} is missing",
            pytrace=False,
        )
        attr = getattr(obj, member)
        if isinstance(attr, property) or isinstance(
            type(obj).__dict__.get(member), property
        ):
            return
        if not callable(attr) and hasattr(attr, "__class__") and not isinstance(
            attr, (bool, int, float, str, bytes, list, dict, set, tuple)
        ):
            return
        assert callable(attr), f"{contract_path}.{member if contract_path else member} is not callable"


class TestContractDiscovery:
    """Meta-tests: verify the contract discovery is sound."""

    def test_contract_has_entries(self):
        total = sum(len(v) for v in CONTRACT.values())
        assert total > 0, "CONTRACT is empty"

    def test_discovered_known_sub_objects(self):
        for sub in ("tray", "status", "channels", "progress", "inv", "login", "websockets"):
            assert sub in CONTRACT, f"Expected sub-object '{sub}' not found in contract"

    def test_discovered_known_top_level_methods(self):
        top = CONTRACT.get("", set())
        for method in ("print", "close", "start", "stop", "save", "display_drop", "clear_drop", "prevent_close"):
            assert method in top, f"Expected top-level method '{method}' not found in contract"
