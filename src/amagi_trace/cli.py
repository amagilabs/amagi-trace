"""amagi-trace command line."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import zipfile
from typing import Optional

from . import __version__
from .parse import NotATrace, load
from .render import Options, render


def find_traces(paths: list) -> list:
    """Expand files/dirs into trace zip paths (any zip that holds a *.trace member)."""
    found: list = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith(".zip"):
                        fp = os.path.join(root, f)
                        if _is_trace(fp):
                            found.append(fp)
        elif os.path.isfile(p):
            found.append(p)
    return sorted(dict.fromkeys(found))


def _is_trace(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.endswith(".trace") for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def slugify(name: str, taken: set) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:60] or "test"
    if s in taken:
        s = f"{s}-{hashlib.sha1(name.encode()).hexdigest()[:6]}"
        n = 2
        base = s
        while s in taken:
            s = f"{base}-{n}"
            n += 1
    taken.add(s)
    return s


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="amagi-trace",
        description="Turn Playwright trace.zip files (or a test-results/ folder) into one markdown file "
        "per failed test, readable by Claude Code, Codex or any other agent.",
    )
    p.add_argument("paths", nargs="+", help="trace.zip file(s) and/or folder(s) to search, e.g. test-results/")
    p.add_argument("-o", "--out", default="trace-md", help="output folder (default: ./trace-md)")
    p.add_argument("--stdout", action="store_true", help="print the markdown instead of writing files")
    p.add_argument("--all", action="store_true", help="also write passing tests (default: failures only)")
    p.add_argument("--all-console", action="store_true", help="include every console message, not just errors/warnings")
    p.add_argument("--hooks", action="store_true", help="include fixture and hook steps in the step list")
    p.add_argument("--max-dom", type=int, default=80, metavar="N", help="max DOM text lines (default 80)")
    p.add_argument("--max-steps", type=int, default=60, metavar="N", help="max steps listed (default 60)")
    p.add_argument("--source-dir", metavar="DIR", help="folder holding the spec files, if the trace was recorded on another machine (CI)")
    p.add_argument("--no-screenshots", action="store_true", help="do not copy screenshots next to the markdown")
    p.add_argument("--version", action="version", version=f"amagi-trace {__version__}")
    return p


def main(argv: Optional[list] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    opts = Options(max_dom=args.max_dom, max_steps=args.max_steps, all_console=args.all_console,
                   show_hooks=args.hooks, source_dir=args.source_dir)
    traces = find_traces(args.paths)
    if not traces:
        print("amagi-trace: no Playwright trace zips found in: " + ", ".join(args.paths), file=sys.stderr)
        return 2
    results = []
    skipped = 0
    for tp in traces:
        try:
            t = load(tp)
        except NotATrace as e:
            print(f"amagi-trace: skipping {e}", file=sys.stderr)
            skipped += 1
            continue
        r = render(t, opts)
        results.append((t, r))
    if not results:
        print("amagi-trace: none of the inputs was a Playwright trace", file=sys.stderr)
        return 2
    selected = [(t, r) for t, r in results if args.all or t.failed]
    n_pass = len(results) - len([1 for t, _ in results if t.failed])
    if args.stdout:
        for _t, r in selected:
            print(r.markdown)
            print("\n---\n")
        print(f"amagi-trace: {len(selected)} of {len(results)} trace(s) shown", file=sys.stderr)
        return 0
    if not selected:
        print(f"amagi-trace: read {len(results)} trace(s), none failed. Nothing written (use --all to write passing tests too).")
        return 0
    os.makedirs(args.out, exist_ok=True)
    taken: set = set()
    index = ["# Playwright failures", "", f"{len(selected)} of {len(results)} trace(s) written by amagi-trace {__version__}.", ""]
    for t, r in selected:
        slug = slugify(r.test_title, taken)
        text = r.markdown
        if r.screenshot_src and not args.no_screenshots:
            kind, ref = r.screenshot_src
            dest_dir = os.path.join(args.out, slug)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "screenshot" + r.screenshot_ext)
            if kind == "file":
                shutil.copyfile(ref, dest)
            else:
                data = t.read(ref)
                if data is not None:
                    with open(dest, "wb") as f:
                        f.write(data)
            if os.path.isfile(dest):
                text += f"\n## Screenshot\n\n![screenshot at failure]({slug}/screenshot{r.screenshot_ext})\n"
        with open(os.path.join(args.out, slug + ".md"), "w", encoding="utf-8") as f:
            f.write(text)
        index.append(f"- [{r.status}] [{r.test_title}]({slug}.md)" + (f" `{r.location}`" if r.location else "") + (f": {r.error_head}" if r.error_head else ""))
    with open(os.path.join(args.out, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    print(f"amagi-trace: read {len(results)} trace(s): {len(results) - n_pass} failed, {n_pass} passed"
          + (f", {skipped} skipped" if skipped else "") + f". Wrote {len(selected)} file(s) to {args.out}/")
    for t, r in selected:
        print(f"  [{r.status}] {r.test_title}: {r.error_head[:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
