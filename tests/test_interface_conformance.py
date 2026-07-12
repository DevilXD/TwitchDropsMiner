"""Verify WebUIManager exposes the same interface as the tkinter GUIManager.

Three layers of checks, all of which catch breakage from upstream merges:
1. Existence: every attribute and method the backend calls on .gui must
   exist on WebUIManager (built by AST-parsing gui.py + scanning backend
   call sites, including alias tracking).
2. Signatures: async-ness, keyword-only params, and defaults must match
   between gui.py and webui (mismatch would cause TypeError at call site).
3. Edge cases: the gui.help._invalidate_button.config(state=...) two-level
   private attribute chain from twitch.py, and detection of new untracked
   gui sub-object aliases introduced by upstream changes.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
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
_GUI_CLASSES = {
    node.name: node for node in ast.walk(GUI_TREE) if isinstance(node, ast.ClassDef)
}


def _public_members(cls_node: ast.ClassDef) -> tuple[list[str], list[str]]:
    methods, props = [], []
    for item in cls_node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = item.name
        if name.startswith("_"):
            continue
        is_prop = any(
            isinstance(d, ast.Name) and d.id == "property" for d in item.decorator_list
        )
        (props if is_prop else methods).append(name)
    return methods, props


def _gui_manager_attr_to_class() -> dict[str, str]:
    """Map GUIManager attribute names to their widget class names."""
    gman = _GUI_CLASSES["GUIManager"]
    init = next(
        n for n in gman.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    result = {}
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
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
        if (
            not callable(attr)
            and hasattr(attr, "__class__")
            and not isinstance(
                attr, (bool, int, float, str, bytes, list, dict, set, tuple)
            )
        ):
            return
        assert callable(
            attr
        ), f"{contract_path}.{member if contract_path else member} is not callable"


class TestContractDiscovery:
    """Meta-tests: verify the contract discovery is sound."""

    def test_contract_has_entries(self):
        total = sum(len(v) for v in CONTRACT.values())
        assert total > 0, "CONTRACT is empty"

    def test_discovered_known_sub_objects(self):
        for sub in (
            "tray",
            "status",
            "channels",
            "progress",
            "inv",
            "login",
            "websockets",
        ):
            assert sub in CONTRACT, f"Expected sub-object '{sub}' not found in contract"

    def test_discovered_known_top_level_methods(self):
        top = CONTRACT.get("", set())
        for method in (
            "print",
            "close",
            "start",
            "stop",
            "save",
            "display_drop",
            "clear_drop",
            "prevent_close",
        ):
            assert (
                method in top
            ), f"Expected top-level method '{method}' not found in contract"


# ---------------------------------------------------------------------------
# Signature conformance — verify async-ness and parameter shapes match
# ---------------------------------------------------------------------------


def _ast_signature(cls_node: ast.ClassDef, method_name: str) -> tuple | None:
    """Extract a simplified signature from the AST: (is_async, params, kwonly, defaults, has_vararg).

    Returns ("property",) for @property methods.
    Returns None if the method is not found on the class.
    """
    for item in cls_node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if item.name != method_name:
            continue
        # Check for @property decorator
        is_prop = any(
            isinstance(d, ast.Name) and d.id == "property" for d in item.decorator_list
        )
        if is_prop:
            return ("property",)
        args = item.args
        is_async = isinstance(item, ast.AsyncFunctionDef)

        # Positional params (skip self), posonly params
        posonly = [a.arg for a in (args.posonlyargs or [])]
        regular = [a.arg for a in args.args]
        if regular and regular[0] == "self":
            regular = regular[1:]
        params = posonly + regular

        # Keyword-only params
        kwonly = [a.arg for a in (args.kwonlyargs or [])]

        # Defaults: aligned from the right for positional args
        n_defaults = len(args.defaults)
        n_params = len(posonly) + len(regular)
        defaulted = set()
        if n_defaults > 0:
            defaulted_params = (posonly + regular)[n_params - n_defaults :]
            defaulted.update(defaulted_params)

        # kwonly defaults: aligned positionally (None means no default)
        for i, d in enumerate(args.kw_defaults or []):
            if d is not None:
                defaulted.add(kwonly[i])

        has_vararg = args.vararg is not None
        has_kwarg = args.kwarg is not None

        return (is_async, params, kwonly, defaulted, has_vararg, has_kwarg)
    return None


def _inspect_signature(obj, method_name: str) -> tuple | None:
    """Extract the same simplified signature from a live object via inspect."""
    attr = getattr(obj, method_name, None)
    if attr is None:
        return None
    # Unwrap classmethod/staticmethod/property
    if isinstance(attr, property):
        return ("property",)
    is_async = asyncio.iscoroutinefunction(attr)
    try:
        sig = inspect.signature(attr)
    except (ValueError, TypeError):
        return None
    params = []
    kwonly = []
    defaults = set()
    has_vararg = False
    has_kwarg = False
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            has_vararg = True
            continue
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            has_kwarg = True
            continue
        if p.kind == inspect.Parameter.KEYWORD_ONLY:
            kwonly.append(name)
        else:
            params.append(name)
        if p.default is not inspect.Parameter.empty:
            defaults.add(name)
    return (is_async, params, kwonly, defaults, has_vararg, has_kwarg)


def _build_signature_contract() -> dict[str, dict[str, tuple]]:
    """Build {attr_path: {method_name: ast_signature}} for all contract methods."""
    sigs: dict[str, dict[str, tuple]] = {}
    # Manager level
    gman = _GUI_CLASSES["GUIManager"]
    mgr_sigs = {}
    for method in CONTRACT.get("", set()):
        sig = _ast_signature(gman, method)
        if sig is not None:
            mgr_sigs[method] = sig
    if mgr_sigs:
        sigs[""] = mgr_sigs
    # Sub-objects
    for attr, cls_name in _ATTR_TO_CLASS.items():
        if attr not in CONTRACT:
            continue
        cls_node = _GUI_CLASSES.get(cls_name)
        if cls_node is None:
            continue
        sub_sigs = {}
        for method in CONTRACT[attr]:
            sig = _ast_signature(cls_node, method)
            if sig is not None:
                sub_sigs[method] = sig
        if sub_sigs:
            sigs[attr] = sub_sigs
    return sigs


SIG_CONTRACT = _build_signature_contract()


class TestSignatureConformance:
    """Verify async-ness and parameter shapes match between gui.py and webui.

    A single test iterates all contract methods, comparing three properties:
    - sync vs async (mismatch would cause TypeError at call site)
    - keyword-only params (mismatch would cause unexpected positional args)
    - which params have defaults (mismatch would change call semantics)

    All mismatches are collected and reported in one failure message so a
    single upstream merge that breaks multiple methods is easy to diagnose.
    """

    def test_signatures_match(self, webui_manager):
        mismatches: list[str] = []

        for path, methods in SIG_CONTRACT.items():
            for method in methods:
                gui_sig = SIG_CONTRACT[path][method]
                if gui_sig[0] == "property":
                    continue

                if path == "":
                    obj = webui_manager
                else:
                    obj = webui_manager
                    for part in path.split("."):
                        obj = getattr(obj, part)

                webui_sig = _inspect_signature(obj, method)
                if webui_sig is None:
                    mismatches.append(f"{path}.{method}: missing on webui")
                    continue

                label = f"{path}.{method}" if path else method

                gui_async, webui_async = gui_sig[0], webui_sig[0]
                if gui_async != webui_async:
                    mismatches.append(
                        f"{label}: async mismatch "
                        f"(gui.py={'async' if gui_async else 'sync'}, "
                        f"webui={'async' if webui_async else 'sync'})"
                    )

                gui_kwonly, webui_kwonly = set(gui_sig[2]), set(webui_sig[2])
                if gui_kwonly != webui_kwonly:
                    mismatches.append(
                        f"{label}: keyword-only mismatch "
                        f"(gui.py={sorted(gui_kwonly)}, webui={sorted(webui_kwonly)})"
                    )

                gui_defaults, webui_defaults = gui_sig[3], webui_sig[3]
                if gui_defaults != webui_defaults:
                    mismatches.append(
                        f"{label}: defaults mismatch "
                        f"(gui.py={sorted(gui_defaults)}, webui={sorted(webui_defaults)})"
                    )

        assert (
            not mismatches
        ), "Signature mismatches between gui.py and webui:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# Invalidate button chain — gui.help._invalidate_button.config(state=...)
# ---------------------------------------------------------------------------


class TestInvalidateButtonChain:
    """Verify the two-level private attribute chain from twitch.py works."""

    def test_full_chain_pattern(self, webui_manager):
        """Exact pattern from twitch.py:102, 119, 429."""
        webui_manager.help._invalidate_button.config(state="disabled")
        webui_manager.help._invalidate_button.config(state="disabled")
        webui_manager.help._invalidate_button.config(state="normal")


# ---------------------------------------------------------------------------
# Alias tracking — detect untracked gui sub-object aliases in backend code
# ---------------------------------------------------------------------------


class TestAliasTracking:
    """Fail if a backend file assigns a gui sub-object to a variable that's not in _ALIAS_MAP."""

    @staticmethod
    def _scan_for_aliases() -> dict[str, str]:
        """AST-scan backend files for `var = ...gui.<attr>` assignments.

        Returns {var_name: gui_attr}. Handles both ast.Assign and ast.AnnAssign
        (typed assignments). Skips `self.<attr> = ...` (target is ast.Attribute).
        """
        found: dict[str, str] = {}
        for py_file in PROJECT_ROOT.rglob("*.py"):
            rel = py_file.relative_to(PROJECT_ROOT)
            if any(part in EXCLUDED_DIRS for part in rel.parts):
                continue
            if rel.name in EXCLUDED_FILES:
                continue
            source = py_file.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                var_name = None
                value = None
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_name = target.id
                            value = node.value
                            break
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name) and node.value is not None:
                        var_name = node.target.id
                        value = node.value
                if var_name is None or value is None:
                    continue
                if var_name.startswith("__"):
                    continue
                # Check if value is `something.gui.<attr>` (possibly multi-level)
                if isinstance(value, ast.Attribute):
                    attr_chain = []
                    cur = value
                    while isinstance(cur, ast.Attribute):
                        attr_chain.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        attr_chain.append(cur.id)
                    attr_chain.reverse()
                    # attr_chain is like ["self", "_twitch", "gui", "login"]
                    if "gui" in attr_chain:
                        gui_idx = attr_chain.index("gui")
                        if gui_idx + 1 < len(attr_chain):
                            gui_attr = attr_chain[gui_idx + 1]
                            found[var_name] = gui_attr
        return found

    def test_no_new_untracked_aliases(self):
        found_aliases = self._scan_for_aliases()
        # Filter out class names (type annotations caught by AnnAssign)
        # and known gui.py class names that appear in typed assignments
        gui_class_names = set(_GUI_CLASSES.keys())
        candidates = {
            var: attr
            for var, attr in found_aliases.items()
            if var not in _ALIAS_MAP
            and var not in gui_class_names
            and not var[0].isupper()
        }
        # Distinguish sub-object aliases (var.method()) from method aliases (var(args)).
        # Only sub-object aliases need _ALIAS_MAP tracking — method aliases are
        # already captured by the shallow/deep regex on the assignment line itself.
        _ALIAS_CALL_RE = re.compile(r"(\w+)\.(\w+)\s*\(")
        untracked: dict[str, str] = {}
        for var, gui_attr in candidates.items():
            used_as_subobject = False
            for py_file in PROJECT_ROOT.rglob("*.py"):
                rel = py_file.relative_to(PROJECT_ROOT)
                if any(part in EXCLUDED_DIRS for part in rel.parts):
                    continue
                if rel.name in EXCLUDED_FILES:
                    continue
                source = py_file.read_text(encoding="utf-8", errors="replace")
                for m in _ALIAS_CALL_RE.finditer(source):
                    if m.group(1) == var and m.group(2) not in ("__call__",):
                        used_as_subobject = True
                        break
                if used_as_subobject:
                    break
            if used_as_subobject:
                untracked[var] = gui_attr
        assert not untracked, (
            "Untracked gui sub-object aliases found in backend code. "
            "Add them to _ALIAS_MAP in this test file:\n"
            + "\n".join(
                f"  {var} → gui.{attr}" for var, attr in sorted(untracked.items())
            )
        )

    def test_known_aliases_are_in_alias_map(self):
        for var, gui_attr in _ALIAS_MAP.items():
            assert isinstance(var, str)
            assert isinstance(gui_attr, str)
            assert (
                gui_attr in _ATTR_TO_CLASS or gui_attr in CONTRACT
            ), f"_ALIAS_MAP entry '{var} → {gui_attr}' references unknown gui attribute"
