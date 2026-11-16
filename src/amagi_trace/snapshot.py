"""Rebuild a Playwright frame snapshot (compact DOM JSON) and render it as text.

Snapshot nodes are either a string (text), ``[TAG, {attrs}, *children]`` or a
reference ``[[snapshots_ago, node_index]]`` to a subtree of an earlier snapshot
of the same frame. Node indexes are post-order and a reference counts as a
nothing: only nodes newly emitted in a snapshot are numbered.
"""
from __future__ import annotations

import re

SKIP_TAGS = {"HEAD", "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "BASE", "META", "LINK", "TITLE", "svg", "SVG", "PATH"}
BLOCK_TAGS = {
    "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "BODY", "DD", "DETAILS", "DIALOG", "DIV", "DL", "DT",
    "FIELDSET", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3", "H4", "H5", "H6", "HEADER",
    "HR", "HTML", "LI", "MAIN", "NAV", "OL", "P", "PRE", "SECTION", "SUMMARY", "TABLE", "TBODY", "TD",
    "TFOOT", "TH", "THEAD", "TR", "UL", "LABEL",
}
LEAF_TAGS = {"INPUT", "TEXTAREA", "SELECT", "IMG", "BUTTON", "A", "H1", "H2", "H3", "H4", "H5", "H6", "LI"}
TARGET = "__playwright_target__"
KEEP_ATTRS = ("id", "class", "name", "type", "placeholder", "href", "role", "data-testid", "aria-label", "disabled")


def is_ref(node) -> bool:
    return isinstance(node, list) and len(node) == 1 and isinstance(node[0], list)


def is_element(node) -> bool:
    return isinstance(node, list) and len(node) >= 2 and isinstance(node[0], str) and isinstance(node[1], dict)


class FrameSnapshots:
    """All snapshots of one frame, in recorded order."""

    def __init__(self) -> None:
        self.raw: list = []
        self._resolved: dict = {}

    def add(self, snap: dict) -> int:
        self.raw.append(snap)
        return len(self.raw) - 1

    def _nodes(self, i: int):
        """Return (root, post-order node list) for snapshot i with refs resolved."""
        if i in self._resolved:
            return self._resolved[i]
        nodes: list = []

        def visit(n):
            if isinstance(n, str):
                nodes.append(n)
                return n
            if is_ref(n):
                ago, idx = n[0][0], n[0][1]
                j = i - ago
                if 0 <= j < i:
                    _, ref_nodes = self._nodes(j)
                    if 0 <= idx < len(ref_nodes):
                        return ref_nodes[idx]
                return ""
            if is_element(n):
                out = [n[0], n[1]]
                for c in n[2:]:
                    out.append(visit(c))
                nodes.append(out)
                return out
            nodes.append("")
            return ""

        root = visit(self.raw[i].get("html"))
        self._resolved[i] = (root, nodes)
        return self._resolved[i]

    def tree(self, i: int):
        return self._nodes(i)[0]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _hidden(attrs: dict) -> bool:
    if "hidden" in attrs:
        return True
    style = (attrs.get("style") or "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _text_of(node) -> str:
    if isinstance(node, str):
        return _norm(node)
    if not is_element(node) or node[0] in SKIP_TAGS or _hidden(node[1]):
        return ""
    if node[0] in ("INPUT", "SELECT", "TEXTAREA"):
        return ""
    return _norm("".join(_text_of(c) for c in node[2:]))


def _label(tag: str, attrs: dict, inner: str) -> str:
    if tag == "BUTTON" or attrs.get("role") == "button":
        return f"[button] {inner.strip()}".rstrip()
    if tag == "A":
        href = attrs.get("href", "")
        return f"[link] {inner.strip()}" + (f" -> {href}" if href else "")
    if tag in ("INPUT", "TEXTAREA", "SELECT"):
        bits = []
        if tag == "INPUT":
            bits.append("type=" + attrs.get("type", "text"))
        for k in ("name", "placeholder"):
            if attrs.get(k):
                bits.append(f"{k}={attrs[k]!r}")
        val = attrs.get("__playwright_value_")
        if val not in (None, ""):
            bits.append(f"value={val!r}")
        if "__playwright_checked_" in attrs:
            bits.append(f"checked={attrs['__playwright_checked_']}")
        if "disabled" in attrs:
            bits.append("disabled")
        return f"[{tag.lower()}] " + " ".join(bits)
    if tag in ("H1", "H2", "H3", "H4", "H5", "H6"):
        return "#" * int(tag[1]) + " " + inner.strip()
    if tag == "LI":
        return "- " + inner.strip()
    if tag == "IMG":
        return f"[img] {attrs.get('alt', '')}".rstrip()
    return inner.strip()


def render_text(root, max_lines: int = 80, max_chars: int = 6000) -> list:
    """Readable outline of the page text, one line per block, target marked."""
    lines: list = []

    def emit(text: str, marked: bool) -> None:
        text = text.strip()
        if text:
            lines.append(text + ("   <-- TARGET" if marked else ""))

    def walk(node) -> str:
        if isinstance(node, str):
            return _norm(node)
        if not is_element(node):
            return ""
        tag, attrs = node[0], node[1]
        if tag in SKIP_TAGS or _hidden(attrs):
            return ""
        marked = TARGET in attrs
        if tag in LEAF_TAGS or attrs.get("role") == "button":
            inner = "" if tag in ("INPUT", "IMG", "SELECT") else _text_of(node)
            emit(_label(tag, attrs, inner), marked)
            return ""
        if tag == "BR":
            return "\n"
        buf = ""
        for c in node[2:]:
            piece = walk(c)
            if "\n" in piece:
                emit(buf, False)
                buf = ""
                piece = piece.replace("\n", "")
            buf += piece
        if tag in BLOCK_TAGS:
            emit(buf, marked and bool(buf.strip()))
            return ""
        return buf

    emit(walk(root), False)
    out: list = []
    total = 0
    for ln in lines:
        total += len(ln)
        if len(out) >= max_lines or total > max_chars:
            out.append(f"... ({len(lines) - len(out)} more lines truncated, raise --max-dom)")
            break
        out.append(ln)
    return out


def find_target(root):
    """First element carrying the target marker (the element the action hit)."""
    if is_element(root):
        if TARGET in root[1]:
            return root
        for c in root[2:]:
            r = find_target(c)
            if r is not None:
                return r
    return None


def outer_summary(node, limit: int = 200) -> str:
    if not is_element(node):
        return ""
    tag, attrs = node[0].lower(), node[1]
    parts = []
    for k in KEEP_ATTRS:
        v = attrs.get(k)
        if v not in (None, ""):
            parts.append(f'{k}="{v}"')
    val = attrs.get("__playwright_value_")
    if val:
        parts.append(f'value="{val}"')
    inner = _text_of(node).strip()
    s = f"<{tag}{(' ' + ' '.join(parts)) if parts else ''}>{inner}</{tag}>"
    return s if len(s) <= limit else s[: limit - 3] + "..."


def page_title(root) -> str:
    if is_element(root):
        if root[0] == "TITLE":
            return _norm("".join(c for c in root[2:] if isinstance(c, str))).strip()
        for c in root[2:]:
            r = page_title(c)
            if r:
                return r
    return ""
