"""HTML authoring utilities for webui components.

Provides a lightweight Tag builder with a NiceGUI-style chainable API that
serializes to raw HTML strings (used where NiceGUI elements are too expensive
to create per-item, e.g. the inventory panel).
"""

from __future__ import annotations

import html as _html


def e(text) -> str:
    """HTML-escape a value for use in element content."""
    return _html.escape(str(text))


def ea(text) -> str:
    """HTML-escape a value for use inside an attribute (quotes escaped too)."""
    return _html.escape(str(text), quote=True)


class Tag:
    """Lightweight HTML builder with a NiceGUI-style chainable API.

    Usage mirrors NiceGUI: .classes() for CSS classes, .props() for HTML
    attributes, .add() to nest children. Serializes to an HTML string via str().

    Example::

        str(
            Tag('div').classes('flex flex-col gap-2').add(
                Tag('span', 'Hello').classes('text-sm text-gray-400'),
                Tag('img').props(src='/static/icon.png', loading='lazy')
                          .classes('w-8 h-8'),
            )
        )
    """

    _VOID = frozenset({"img", "input", "br", "hr", "meta", "link"})

    def __init__(self, tag: str, text: str = ""):
        self._tag = tag
        self._text = text
        self._classes: list[str] = []
        self._attrs: dict[str, str] = {}
        self._children: list["Tag"] = []

    def classes(self, *cls: str) -> "Tag":
        """Add one or more space-separated CSS class strings."""
        for c in cls:
            self._classes.extend(c.split())
        return self

    def props(self, **attrs) -> "Tag":
        """Set HTML attributes. Trailing underscores are stripped so Python
        reserved words can be passed (e.g. for_='x' → for="x")."""
        self._attrs.update({k.rstrip("_"): str(v) for k, v in attrs.items()})
        return self

    def add(self, *children: "Tag") -> "Tag":
        """Append child Tag objects."""
        self._children.extend(children)
        return self

    def __str__(self) -> str:
        cls = f' class="{" ".join(self._classes)}"' if self._classes else ""
        attrs = "".join(f' {k}="{ea(v)}"' for k, v in self._attrs.items())
        if self._tag in self._VOID:
            return f"<{self._tag}{cls}{attrs}>"
        inner = (e(self._text) if self._text else "") + "".join(
            str(c) for c in self._children
        )
        return f"<{self._tag}{cls}{attrs}>{inner}</{self._tag}>"
