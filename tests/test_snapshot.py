from amagi_trace.snapshot import (
    FrameSnapshots,
    find_target,
    outer_summary,
    page_title,
    render_text,
)

BASE = {
    "html": [
        "HTML", {},
        ["HEAD", {}, ["TITLE", {}, "Shop"], ["SCRIPT", {}, "evil()"]],
        ["BODY", {},
         ["H1", {}, "Checkout"],            # 3? post-order numbering checked below
         ["P", {"id": "status"}, "Ready"],
         ["BUTTON", {"id": "pay"}, "Pay now"]],
    ]
}


def _fs_with_ref():
    fs = FrameSnapshots()
    fs.add(BASE)
    # post-order of BASE: TITLE text0 TITLE1 SCRIPT text2 SCRIPT3 HEAD4 ... find H1 index by search instead
    root, nodes = fs._nodes(0)
    h1_idx = next(i for i, n in enumerate(nodes) if isinstance(n, list) and n[0] == "H1")
    head_idx = next(i for i, n in enumerate(nodes) if isinstance(n, list) and n[0] == "HEAD")
    fs.add({"html": ["HTML", {}, [[1, head_idx]], ["BODY", {}, [[1, h1_idx]],
            ["P", {"id": "status", "__playwright_target__": ""}, "Error 500"]]]})
    return fs


def test_reference_resolves_to_earlier_snapshot_node():
    fs = _fs_with_ref()
    text = render_text(fs.tree(1))
    assert "# Checkout" in text
    assert any(ln.startswith("Error 500") for ln in text)


def test_refs_do_not_consume_node_indexes():
    fs = _fs_with_ref()
    fs.add({"html": ["HTML", {}, [[1, 0]]]})  # idx 0 of snapshot 1 = first *new* node = "Error 500" text
    _root, nodes = fs._nodes(1)
    assert nodes[0] == "Error 500"
    assert fs.tree(2)[2] == "Error 500"


def test_bad_reference_is_ignored_not_fatal():
    fs = FrameSnapshots()
    fs.add({"html": ["HTML", {}, [[5, 99]], ["BODY", {}, "hello"]]})
    assert render_text(fs.tree(0)) == ["hello"]


def test_scripts_and_hidden_nodes_skipped():
    root = ["HTML", {}, ["BODY", {}, ["SCRIPT", {}, "x=1"], ["DIV", {"style": "display: none"}, "secret"], ["P", {}, "shown"]]]
    assert render_text(root) == ["shown"]


def test_target_marker_and_summary():
    root = ["BODY", {}, ["BUTTON", {"id": "go", "__playwright_target__": "", "type": "button"}, "Go"]]
    tgt = find_target(root)
    assert tgt[1]["id"] == "go"
    assert outer_summary(tgt) == '<button id="go" type="button">Go</button>'
    assert render_text(root) == ["[button] Go   <-- TARGET"]


def test_input_values_and_links():
    root = ["BODY", {}, ["INPUT", {"type": "email", "placeholder": "you@x.co", "__playwright_value_": "a@b.co"}],
            ["A", {"href": "/help"}, "Help"], ["INPUT", {"type": "checkbox", "__playwright_checked_": "true"}]]
    out = render_text(root)
    assert "value='a@b.co'" in out[0]
    assert out[1] == "[link] Help -> /help"
    assert "checked=true" in out[2]


def test_truncation_notice():
    root = ["BODY", {}] + [["P", {}, f"line {i}"] for i in range(10)]
    out = render_text(root, max_lines=3)
    assert len(out) == 4 and "more lines truncated" in out[-1]


def test_page_title():
    assert page_title(BASE["html"]) == "Shop"
