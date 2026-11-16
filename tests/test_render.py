from amagi_trace.parse import load
from amagi_trace.render import Options, render, title_of
from conftest import make_trace


def test_title_parsed_from_playwright_title(checkout_zip):
    assert title_of(load(checkout_zip)) == "checkout shows confirmation"


def test_failure_report_has_the_useful_parts(checkout_zip):
    r = render(load(checkout_zip))
    md = r.markdown
    assert r.status == "FAILED" and r.location == "shop.spec.js:9"
    assert 'Expected: "Payment confirmed"' in md and 'Received: "Error 500"' in md
    assert "Locator: `locator('#status')`" in md
    assert "[FAIL] Expect" in md and "[ok] Click" in md
    assert "Payment widget failed to initialise" in md
    assert "`POST https://shop.test/api/charge` -> **500" in md
    assert "response body: `boom`" in md
    assert "Target element: `<p id=\"status\">Error 500</p>`" in md
    assert "Error 500   <-- TARGET" in md
    assert "\x1b" not in md


def test_source_excerpt_comes_from_zip(checkout_zip):
    md = render(load(checkout_zip)).markdown
    assert ">    9 |" in md and "toHaveText('Payment confirmed'" in md


def test_source_dir_override(tmp_path, checkout_zip):
    (tmp_path / "shop.spec.js").write_text("\n" * 8 + "LINE_NINE\n")
    md = render(load(checkout_zip), Options(source_dir=str(tmp_path))).markdown
    # on-disk path from the trace does not exist, so --source-dir wins over the zip copy
    assert "LINE_NINE" in md


def test_after_failure_hooks_hidden_unless_asked(checkout_zip):
    t = load(checkout_zip)
    assert "After Hooks" not in render(t).markdown
    assert "After Hooks" in render(t, Options(show_hooks=True)).markdown


def test_timeout_failure_uses_call_log_and_aria(timeout_zip):
    md = render(load(timeout_zip)).markdown
    assert "TimeoutError: locator.click" in md
    assert "Internal selector: `internal:role=button[name=\"Refund\"i]`" in md
    assert "ARIA snapshot" in md and 'button "Pay now"' in md
    assert "None recorded." in md


def test_page_error_and_network_failure_listed(coupon_zip):
    md = render(load(coupon_zip)).markdown
    assert "[pageerror]" in md and "coupon widget exploded" in md
    assert "**no response**" in md and 'request body: `{"code":"SAVE10"}`' in md


def test_passing_trace_renders_passed(passing_zip):
    r = render(load(passing_zip))
    assert r.status == "PASSED" and "## Failure" not in r.markdown


def test_screenshot_prefers_playwright_png(checkout_zip):
    r = render(load(checkout_zip))
    assert r.screenshot_src[0] == "file" and r.screenshot_src[1].endswith(".png")


def test_screenshot_falls_back_to_last_screencast_frame(tmp_path):
    path = make_trace(
        tmp_path / "t.zip",
        [{"type": "context-options", "origin": "testRunner", "monotonicTime": 0},
         {"type": "before", "callId": "e@1", "stepId": "e@1", "startTime": 1, "class": "Test", "method": "expect", "title": "Expect x"},
         {"type": "after", "callId": "e@1", "endTime": 50, "error": {"message": "nope"}}],
        [{"type": "context-options", "browserName": "chromium", "title": "a.spec.ts:1 › lonely", "monotonicTime": 0},
         {"type": "screencast-frame", "file": "screencast/a.jpeg", "timestamp": 10},
         {"type": "screencast-frame", "file": "screencast/b.jpeg", "timestamp": 40},
         {"type": "screencast-frame", "file": "screencast/c.jpeg", "timestamp": 900}],
    )
    r = render(load(path))
    assert r.screenshot_src == ("zip", "screencast/b.jpeg")
    assert r.screenshot_ext == ".jpeg"


def test_repeated_console_lines_are_collapsed(tmp_path):
    ev = [{"type": "context-options", "browserName": "chromium", "title": "a.spec.ts:1 › rep", "monotonicTime": 0}]
    ev += [{"type": "console", "messageType": "error", "text": "same", "location": {"url": "http://x/a.js", "lineNumber": 1}, "time": i} for i in range(5)]
    ev += [{"type": "before", "callId": "call@1", "stepId": "pw:api@1", "class": "Frame", "method": "click", "params": {}, "startTime": 1},
           {"type": "after", "callId": "call@1", "endTime": 2, "error": {"message": "x"}}]
    path = make_trace(tmp_path / "c.zip", [{"type": "context-options", "origin": "testRunner", "monotonicTime": 0}], ev)
    md = render(load(path)).markdown
    assert md.count("same") == 1 and "(x5)" in md
