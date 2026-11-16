"""Turn a parsed Trace into one markdown document."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .parse import Trace, Step, source_member
from .snapshot import find_target, outer_summary, page_title, render_text


@dataclass
class Options:
    max_dom: int = 80
    max_steps: int = 60
    max_console: int = 25
    max_network: int = 20
    all_console: bool = False
    show_hooks: bool = False
    source_dir: Optional[str] = None


@dataclass
class Rendered:
    markdown: str
    test_name: str
    location: str
    status: str
    error_head: str
    screenshot_src: Optional[tuple] = None  # ("zip", member) | ("file", path)
    screenshot_ext: str = ".png"
    extras: dict = field(default_factory=dict)


def test_name(t: Trace) -> str:
    title = t.title or ""
    m = re.match(r"^(\S+?):(\d+)\s+\S+\s+(.*)$", title)
    if m:
        return m.group(3).strip()
    return title or os.path.basename(os.path.dirname(os.path.abspath(t.source))) or os.path.basename(t.source)


def _location(t: Trace) -> str:
    for fr in t.test_error_stack or []:
        if fr.get("file"):
            return f"{os.path.basename(fr['file'])}:{fr.get('line', '?')}"
    m = re.match(r"^(\S+?:\d+)\s", t.title or "")
    return m.group(1) if m else ""


def _fmt_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "?"
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _failing_step(t: Trace) -> Optional[Step]:
    """Deepest erroring user-level step; falls back to the first erroring step."""
    failed = [s for s in t.steps if s.error and not s.is_noise]
    if not failed:
        failed = [s for s in t.steps if s.error]
    if not failed:
        return None
    ids = {s.call_id for s in failed}
    parents = {s.parent_id for s in failed}
    leaves = [s for s in failed if s.call_id not in parents]
    return (leaves or failed)[0] if ids else None


def _step_depth(step: Step, by_id: dict) -> int:
    d = 0
    p = step.parent_id
    while p and p in by_id:
        d += 1
        p = by_id[p].parent_id
    return d


def _under_noise(step: Step, by_id: dict) -> bool:
    p = step.parent_id
    while p and p in by_id:
        if by_id[p].is_noise:
            return True
        p = by_id[p].parent_id
    return False


def _step_label(s: Step) -> str:
    label = s.title or s.method
    if s.subtitle:
        label += f" {s.subtitle}"
    p = s.params or {}
    extra = []
    if s.method == "expect" and "expected" in p:
        extra.append(f"expected {json.dumps(p['expected'])}")
    return label + (f" [{', '.join(extra)}]" if extra else "")


def _steps_section(t: Trace, opts: Options, failing: Optional[Step]) -> list:
    by_id = {s.call_id: s for s in t.steps}
    rows = []
    for s in t.steps:
        if not opts.show_hooks and (s.is_noise or _under_noise(s, by_id)):
            continue
        if failing is not None and not opts.show_hooks and s.start > failing.start:
            continue
        rows.append(s)
    out = []
    shown = rows[: opts.max_steps]
    for i, s in enumerate(shown, 1):
        mark = "FAIL" if s.error else ("ok" if s.end is not None else "?")
        indent = "  " * _step_depth(s, by_id)
        out.append(f"{indent}{i}. [{mark}] {_step_label(s)} ({_fmt_ms(s.duration_ms)})")
    if len(rows) > len(shown):
        out.append(f"... {len(rows) - len(shown)} more steps (raise --max-steps)")
    return out


def _collapse(lines: list) -> list:
    """Drop repeated lines (keeping first-seen order) and note how often each occurred."""
    counts: dict = {}
    for ln in lines:
        ln = ln.strip()
        if ln:
            counts[ln] = counts.get(ln, 0) + 1
    return [ln + (f"  (x{n})" if n > 1 else "") for ln, n in counts.items()]


def _call_for_step(t: Trace, step: Optional[Step]):
    if step is None:
        return None
    for c in t.calls.values():
        if c.step_id == step.call_id:
            return c
    return None


def _snapshot_for(t: Trace, call) -> Optional[tuple]:
    """Pick the page snapshot that best shows the page at failure time."""
    if call is not None:
        for phase in ("after", "action", "before"):
            for cid, ph, fk, idx, main, ts in reversed(t.snap_index):
                if cid == call.call_id and ph == phase and main:
                    return fk, idx
    mains = [x for x in t.snap_index if x[4]]
    if mains:
        _, _, fk, idx, _, _ = mains[-1]
        return fk, idx
    return None


def _source_excerpt(t: Trace, file_path: str, line: int, opts: Options) -> list:
    text = None
    for cand in (file_path, os.path.join(opts.source_dir, os.path.basename(file_path)) if opts.source_dir else None):
        if cand and os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                break
            except OSError:
                pass
    if text is None:
        text = source_member(t, file_path)
    if not text:
        return []
    src = text.splitlines()
    lo, hi = max(1, line - 4), min(len(src), line + 3)
    return [f"{'>' if n == line else ' '} {n:>4} | {src[n - 1]}" for n in range(lo, hi + 1)]


def _context_aria(trace_path: str) -> Optional[str]:
    """YAML ARIA snapshot Playwright writes next to the trace (error-context.md)."""
    p = os.path.join(os.path.dirname(os.path.abspath(trace_path)), "error-context.md")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    blocks = re.findall(r"```yaml\n(.*?)```", txt, re.S)
    return blocks[0].rstrip() if blocks else None


def _adjacent_screenshot(trace_path: str) -> Optional[str]:
    d = os.path.dirname(os.path.abspath(trace_path))
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return None
    for n in names:
        if n.lower().endswith(".png") and "fail" in n.lower():
            return os.path.join(d, n)
    return None


def render(t: Trace, opts: Optional[Options] = None) -> Rendered:
    opts = opts or Options()
    name = test_name(t)
    failing = _failing_step(t)
    status = "FAILED" if t.failed else "PASSED"
    msg = t.test_error or (failing.error if failing else "") or ""
    for c in t.calls.values():
        if not msg and c.error:
            msg = c.error
    head = next((ln.strip() for ln in msg.splitlines() if ln.strip()), "")
    loc = _location(t)
    md: list = [f"# {name}", ""]
    meta = [f"- Status: **{status}**"]
    if loc:
        meta.append(f"- Test location: `{loc}`")
    if t.browser:
        meta.append(f"- Browser: {t.browser}")
    meta.append(f"- Trace: `{os.path.basename(os.path.dirname(os.path.abspath(t.source))) + '/' + os.path.basename(t.source)}`")
    md += meta + [""]

    if msg:
        md += ["## Failure", "", "```", msg.strip(), "```", ""]
    call = _call_for_step(t, failing)
    if failing is not None:
        md += ["### Failing step", ""]
        md.append(f"- Step: {_step_label(failing)}")
        loc_param = (failing.params or {}).get("locator") or failing.subtitle
        if loc_param:
            md.append(f"- Locator: `{loc_param}`")
        if call is not None and call.params.get("selector"):
            md.append(f"- Internal selector: `{call.params['selector']}`")
        if failing.stack:
            fr = failing.stack[0]
            md.append(f"- At: `{os.path.basename(fr.get('file', ''))}:{fr.get('line')}:{fr.get('column')}`")
        md.append("")
    if t.test_error_stack:
        fr = t.test_error_stack[0]
        exc = _source_excerpt(t, fr.get("file", ""), fr.get("line", 0), opts)
        if exc:
            md += ["### Test source", "", "```", *exc, "```", ""]
    if call is not None and call.logs and "Call log:" not in msg:
        logs = _collapse(call.logs)
        md += ["### What Playwright was doing (call log)", "", "```"]
        md += logs[:12]
        if len(logs) > 12:
            md.append(f"... {len(logs) - 12} more lines")
        md += ["```", ""]

    steps = _steps_section(t, opts, failing)
    if steps:
        md += ["## Steps", "", *steps, ""]

    # console + page errors
    cons = [c for c in t.console if opts.all_console or c.kind in ("error", "warning", "warn", "assert")]
    cons_lines = []
    for c in cons:
        where = f" ({os.path.basename(c.url)}:{c.line})" if c.url and not c.url.startswith("http") else (f" ({c.url})" if c.url else "")
        cons_lines.append(f"[{c.kind}] +{t.rel(c.time):.1f}s {c.text}{where}")
    cons_lines = _collapse(cons_lines)
    pe = [f"[pageerror] +{t.rel(ts):.1f}s {m}" + (f"\n    {st.splitlines()[1].strip()}" if len(st.splitlines()) > 1 else "") for ts, m, st in t.page_errors]
    if cons_lines or pe:
        md += ["## Console and page errors", "", "```", *(pe + cons_lines)[: opts.max_console], "```", ""]
    else:
        md += ["## Console and page errors", "", "None recorded.", ""]

    bad = [n for n in t.network if n.failure or n.status >= 400 or n.status <= 0]
    if bad:
        md += ["## Failed network calls", ""]
        for n in bad[: opts.max_network]:
            st = f"{n.status} {n.status_text}".strip() if n.status > 0 else "no response"
            md.append(f"- `{n.method} {n.url}` -> **{st}**" + (f" ({n.failure})" if n.failure else "") + f" at +{t.rel(n.time):.1f}s")
            if n.post_data:
                md.append(f"  - request body: `{n.post_data[:200].strip()}`")
            if n.body.strip():
                md.append(f"  - response body: `{n.body[:300].strip()}`")
        md.append("")
    else:
        md += ["## Failed network calls", "", f"None (of {len(t.network)} requests recorded).", ""]

    # DOM
    snap = _snapshot_for(t, call)
    if snap is not None:
        fk, idx = snap
        root = t.frames[fk].tree(idx)
        raw = t.frames[fk].raw[idx]
        md += ["## Page at the moment of failure", ""]
        md.append(f"- URL: `{raw.get('frameUrl', '')}`")
        ttl = page_title(root)
        if ttl:
            md.append(f"- Title: {ttl}")
        tgt = find_target(root)
        if tgt is not None:
            md.append(f"- Target element: `{outer_summary(tgt)}`")
        md += ["", "DOM text (hidden elements skipped, form values shown):", "", "```", *render_text(root, max_lines=opts.max_dom), "```", ""]
    aria = _context_aria(t.source)
    if aria:
        md += ["### ARIA snapshot (from Playwright error-context.md)", "", "```yaml", aria, "```", ""]

    shot = None
    ext = ".png"
    adj = _adjacent_screenshot(t.source)
    if adj:
        shot = ("file", adj)
        ext = os.path.splitext(adj)[1] or ".png"
    elif t.screencast:
        end_t = (failing.end if failing and failing.end else None)
        cands = [f for ts, f in t.screencast if end_t is None or ts <= end_t + 50] or [t.screencast[-1][1]]
        shot = ("zip", cands[-1])
        ext = os.path.splitext(cands[-1])[1] or ".jpeg"
    return Rendered("\n".join(md).rstrip() + "\n", name, loc, status, head, shot, ext)
