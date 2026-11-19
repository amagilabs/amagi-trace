import os
import shutil
import subprocess
import sys

from amagi_trace.cli import find_traces, main, slugify


def test_find_traces_walks_folder(results_dir):
    found = find_traces([results_dir])
    assert len(found) == 4 and all(p.endswith("trace.zip") for p in found)


def test_find_traces_ignores_non_trace_zip(tmp_path):
    import zipfile

    with zipfile.ZipFile(tmp_path / "other.zip", "w") as z:
        z.writestr("a.txt", "x")
    assert find_traces([str(tmp_path)]) == []


def test_slugify_collisions():
    taken = set()
    a = slugify("Same name", taken)
    b = slugify("Same name", taken)
    assert a == "same-name" and b != a and b.startswith("same-name-")


def test_writes_one_file_per_failure(tmp_path, results_dir, capsys):
    out = tmp_path / "o"
    assert main([results_dir, "-o", str(out)]) == 0
    names = sorted(os.listdir(out))
    assert "index.md" in names
    md = [n for n in names if n.endswith(".md") and n != "index.md"]
    assert len(md) == 3  # the passing test is skipped
    assert (out / "checkout-shows-confirmation" / "screenshot.png").stat().st_size > 100
    body = (out / "checkout-shows-confirmation.md").read_text(encoding="utf-8")
    assert "![screenshot at failure](checkout-shows-confirmation/screenshot.png)" in body
    idx = (out / "index.md").read_text(encoding="utf-8")
    assert "3 of 4 trace(s)" in idx and "checkout-shows-confirmation.md" in idx
    assert "3 failed, 1 passed" in capsys.readouterr().out


def test_all_flag_includes_passing(tmp_path, results_dir):
    out = tmp_path / "o"
    assert main([results_dir, "-o", str(out), "--all"]) == 0
    assert (out / "heading-visible.md").is_file()


def test_stdout_mode_writes_nothing(tmp_path, checkout_zip, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main([checkout_zip, "--stdout"]) == 0
    cap = capsys.readouterr()
    assert "# checkout shows confirmation" in cap.out
    assert os.listdir(tmp_path) == []


def test_no_screenshots(tmp_path, checkout_zip):
    out = tmp_path / "o"
    main([checkout_zip, "-o", str(out), "--no-screenshots"])
    assert not (out / "checkout-shows-confirmation").exists()


def test_passing_only_input_writes_nothing(tmp_path, passing_zip, capsys):
    out = tmp_path / "o"
    assert main([passing_zip, "-o", str(out)]) == 0
    assert not out.exists()
    assert "none failed" in capsys.readouterr().out


def test_no_traces_found_exit_2(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert "no Playwright trace zips" in capsys.readouterr().err


def test_bad_file_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.zip"
    bad.write_text("junk")
    assert main([str(bad)]) == 2


def test_module_entry_point(results_dir, tmp_path):
    env = dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))
    r = subprocess.run([sys.executable, "-m", "amagi_trace", "--version"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "amagi-trace 0.1.1" in r.stdout
