import zipfile

import pytest

from amagi_trace.parse import NotATrace, load, strip_ansi
from conftest import make_trace


def test_strip_ansi():
    assert strip_ansi("\x1b[2mexpect(\x1b[22m\x1b[31mx\x1b[39m") == "expect(x"


def test_real_failing_trace_fields(checkout_zip):
    t = load(checkout_zip)
    assert t.failed and t.browser == "chromium"
    assert "toHaveText" in t.test_error and "\x1b" not in t.test_error
    assert t.test_error_stack[0]["line"] == 9
    assert any(s.method == "expect" and s.error for s in t.steps)


def test_real_trace_console_and_network(checkout_zip):
    t = load(checkout_zip)
    assert any("Payment widget failed" in c.text for c in t.console)
    post = [n for n in t.network if n.method == "POST"]
    assert post and post[0].status == 500 and post[0].body == "boom"


def test_real_trace_aborted_request_and_page_error(coupon_zip):
    t = load(coupon_zip)
    assert any("coupon widget exploded" in m for _ts, m, _s in t.page_errors)
    bad = [n for n in t.network if n.status <= 0 or n.failure]
    assert bad and bad[0].url.endswith("/api/coupon")
    assert bad[0].post_data and "SAVE10" in bad[0].post_data


def test_passing_trace_is_not_failed(passing_zip):
    assert not load(passing_zip).failed


def test_call_ids_link_runner_step_to_browser_call(checkout_zip):
    t = load(checkout_zip)
    step = next(s for s in t.steps if s.error and s.method == "expect")
    assert any(c.step_id == step.call_id and c.method == "expect" for c in t.calls.values())


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_text("nope")
    with pytest.raises(NotATrace):
        load(str(p))


def test_zip_without_trace_member(tmp_path):
    p = tmp_path / "y.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(NotATrace):
        load(str(p))


def test_malformed_lines_are_skipped(tmp_path):
    p = tmp_path / "z.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("trace.trace", '{"type":"context-options","title":"a.spec.ts:1 \\u203a t","browserName":"firefox"}\nnot json\n\n')
    t = load(str(p))
    assert t.browser == "firefox" and not t.failed


def test_step_error_without_runner_error_event(tmp_path):
    path = make_trace(
        tmp_path / "s.zip",
        [{"type": "context-options", "origin": "testRunner", "monotonicTime": 1},
         {"type": "before", "callId": "pw:api@1", "stepId": "pw:api@1", "startTime": 2, "class": "Test", "method": "pw:api", "title": "Click"},
         {"type": "after", "callId": "pw:api@1", "endTime": 5, "error": {"message": "boom"}}],
        [{"type": "context-options", "browserName": "chromium", "title": "a.spec.ts:3 › my test", "monotonicTime": 1}],
    )
    t = load(path)
    assert t.failed and t.failed_steps[0].error == "boom"
