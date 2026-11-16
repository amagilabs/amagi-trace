"""Read a Playwright trace.zip into a plain data model."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional

from .snapshot import FrameSnapshots

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TRACE_NAME = re.compile(r"(^|/)(\d+-)?trace\.trace$|(^|/)test\.trace$")


def strip_ansi(s: str) -> str:
    return ANSI.sub("", s or "")


class NotATrace(Exception):
    pass


@dataclass
class Step:
    call_id: str
    title: str = ""
    subtitle: str = ""
    cls: str = ""
    method: str = ""
    params: dict = field(default_factory=dict)
    start: float = 0.0
    end: Optional[float] = None
    error: Optional[str] = None
    parent_id: Optional[str] = None
    stack: list = field(default_factory=list)
    group: str = ""

    @property
    def duration_ms(self) -> Optional[float]:
        return None if self.end is None else max(0.0, self.end - self.start)

    @property
    def is_noise(self) -> bool:
        return self.cls == "Test" and self.method in ("hook", "fixture")


@dataclass
class BrowserCall:
    call_id: str
    step_id: Optional[str]
    cls: str
    method: str
    params: dict
    start: float
    end: Optional[float] = None
    error: Optional[str] = None
    logs: list = field(default_factory=list)


@dataclass
class ConsoleMsg:
    kind: str
    text: str
    url: str
    line: int
    time: float


@dataclass
class NetEntry:
    method: str
    url: str
    status: int
    status_text: str
    time: float
    failure: str
    body: str
    post_data: str
    mime: str


@dataclass
class Trace:
    source: str
    title: str = ""
    browser: str = ""
    wall_time: float = 0.0
    base_time: Optional[float] = None
    test_error: Optional[str] = None
    test_error_stack: list = field(default_factory=list)
    has_test_events: bool = False
    steps: list = field(default_factory=list)
    calls: dict = field(default_factory=dict)
    console: list = field(default_factory=list)
    page_errors: list = field(default_factory=list)
    network: list = field(default_factory=list)
    frames: dict = field(default_factory=dict)  # frameId -> FrameSnapshots
    snap_index: list = field(default_factory=list)  # (callId, phase, frameId, idx, isMain, time)
    screencast: list = field(default_factory=list)  # (time, file)
    stacks: dict = field(default_factory=dict)  # call number -> [(file, line, col)]
    names: set = field(default_factory=set)
    _zf: object = None

    def read(self, name: str) -> Optional[bytes]:
        try:
            return self._zf.read(name)
        except KeyError:
            return None

    @property
    def failed_steps(self) -> list:
        return [s for s in self.steps if s.error]

    @property
    def failed(self) -> bool:
        return bool(self.test_error or self.failed_steps or any(c.error for c in self.calls.values()))

    def rel(self, t: float) -> float:
        base = self.base_time if self.base_time is not None else 0.0
        return max(0.0, t - base) / 1000.0


def _lines(data: bytes):
    for raw in data.decode("utf-8", "replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except ValueError:
            continue


def _err_text(err) -> str:
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        return err.get("message") or err.get("value") or json.dumps(err)
    return str(err)


def load(path: str) -> Trace:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise NotATrace(f"{path}: not a readable zip ({e})")
    names = zf.namelist()
    trace_files = [n for n in names if TRACE_NAME.search(n)]
    if not trace_files:
        raise NotATrace(f"{path}: no *.trace member, not a Playwright trace")
    t = Trace(source=path, names=set(names))
    t._zf = zf
    # test.trace (runner steps) first so the title/error win, then browser traces in order
    trace_files.sort(key=lambda n: (not n.endswith("test.trace"), n))
    starts = []
    steps_by_id = {}
    for name in trace_files:
        is_test = name.endswith("test.trace")
        for ev in _lines(zf.read(name)):
            typ = ev.get("type")
            if typ == "context-options":
                if ev.get("monotonicTime") is not None:
                    starts.append(ev["monotonicTime"])
                if is_test:
                    t.has_test_events = True
                else:
                    t.browser = t.browser or ev.get("browserName", "")
                    t.title = t.title or ev.get("title", "")
                    t.wall_time = t.wall_time or ev.get("wallTime", 0)
            elif typ == "before":
                if is_test or ev.get("class") == "Test":
                    s = Step(
                        call_id=ev["callId"], title=strip_ansi(ev.get("title", "")), subtitle=ev.get("subtitle", ""),
                        cls=ev.get("class", ""), method=ev.get("method", ""), params=ev.get("params") or {},
                        start=ev.get("startTime", 0.0), parent_id=ev.get("parentId"), stack=ev.get("stack") or [],
                        group=ev.get("group", ""),
                    )
                    steps_by_id[s.call_id] = s
                    t.steps.append(s)
                else:
                    t.calls[ev["callId"]] = BrowserCall(
                        ev["callId"], ev.get("stepId"), ev.get("class", ""), ev.get("method", ""),
                        ev.get("params") or {}, ev.get("startTime", 0.0),
                    )
            elif typ == "after":
                cid = ev.get("callId")
                if cid in steps_by_id:
                    st = steps_by_id[cid]
                    st.end = ev.get("endTime")
                    if ev.get("error"):
                        st.error = strip_ansi(_err_text(ev["error"]))
                elif cid in t.calls:
                    c = t.calls[cid]
                    c.end = ev.get("endTime")
                    if ev.get("error"):
                        c.error = strip_ansi(_err_text(ev["error"]))
            elif typ == "error" and is_test:
                if t.test_error is None:
                    t.test_error = strip_ansi(ev.get("message", ""))
                    t.test_error_stack = ev.get("stack") or []
            elif typ == "log":
                c = t.calls.get(ev.get("callId"))
                if c is not None:
                    c.logs.append(strip_ansi(ev.get("message", "")))
            elif typ == "console":
                loc = ev.get("location") or {}
                t.console.append(ConsoleMsg(
                    ev.get("messageType", "log"), strip_ansi(ev.get("text", "")), loc.get("url", ""),
                    loc.get("lineNumber", 0), ev.get("time", 0.0),
                ))
            elif typ == "event" and ev.get("method") == "pageError":
                e = (ev.get("params") or {}).get("error") or {}
                inner = e.get("error") or {}
                msg = inner.get("message") or str(e.get("value", "")) or "page error"
                stack = inner.get("stack", "")
                t.page_errors.append((ev.get("time", 0.0), strip_ansi(msg), strip_ansi(stack)))
            elif typ == "screencast-frame":
                t.screencast.append((ev.get("timestamp", 0.0), ev.get("file", "")))
            elif typ == "frame-snapshot":
                snap = ev.get("snapshot") or {}
                fid = snap.get("frameId", "")
                fs = t.frames.setdefault((name, fid), FrameSnapshots())
                idx = fs.add(snap)
                t.snap_index.append((snap.get("callId"), snap.get("phase"), (name, fid), idx,
                                     bool(snap.get("isMainFrame", True)), snap.get("timestamp", 0.0)))
    # network
    for name in [n for n in names if n.endswith("trace.network")]:
        for ev in _lines(zf.read(name)):
            s = ev.get("snapshot")
            if not s:
                continue
            req, resp = s.get("request", {}), s.get("response", {})
            content = resp.get("content", {}) or {}
            body = ""
            mime = content.get("mimeType", "")
            f = content.get("_file")
            if f and ("text" in mime or "json" in mime or "xml" in mime or f.endswith(".dat")):
                raw = zf.read(f) if f in names else b""
                body = raw[:2000].decode("utf-8", "replace") if raw and b"\x00" not in raw[:200] else ""
            post = ""
            pd = req.get("postData") or {}
            if pd.get("_file") and pd["_file"] in names:
                post = zf.read(pd["_file"])[:1000].decode("utf-8", "replace")
            elif pd.get("text"):
                post = pd["text"][:1000]
            t.network.append(NetEntry(
                req.get("method", "GET"), req.get("url", ""), int(resp.get("status", 0) or 0),
                resp.get("statusText", ""), s.get("_monotonicTime", 0.0), s.get("_failureText", "") or "",
                body, post, mime,
            ))
    # stacks (callNumber -> frames)
    for name in [n for n in names if n.endswith("trace.stacks")]:
        try:
            d = json.loads(zf.read(name))
        except ValueError:
            continue
        files = d.get("files", [])
        for entry in d.get("stacks", []):
            if len(entry) == 2:
                t.stacks[entry[0]] = [(files[f[0]] if f[0] < len(files) else "", f[1], f[2]) for f in entry[1]]
    t.base_time = min(starts) if starts else None
    return t


def source_member(trace: Trace, file_path: str) -> Optional[str]:
    """Spec source bundled in the zip (src/<sha1 of path>.<ext>), if present."""
    sha = hashlib.sha1(file_path.encode("utf-8")).hexdigest()
    for n in trace.names:
        if n.startswith("src/") and sha in n:
            data = trace.read(n)
            return data.decode("utf-8", "replace") if data is not None else None
    return None
