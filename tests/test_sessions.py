"""Recovery operations retain edited scripts and never discard later notebook edits."""

import json
from pathlib import Path

import nbformat
import pytest

from notebook_workflow import WorkflowError, abort, apply, prepare, resume, restore, review, sessions, status
from notebook_workflow.core import refresh_state
from notebook_workflow.cli import main


@pytest.fixture(params=["python", "r"])
def notebook(tmp_path, request):
    language = request.param
    path = tmp_path / "notebooks" / "analysis.ipynb"
    path.parent.mkdir()
    path.write_text(json.dumps(nbformat.v4.new_notebook(metadata={
        "kernelspec": {"language": language, "name": "python3" if language == "python" else "ir", "display_name": language}},
        cells=[nbformat.v4.new_code_cell("x = 1" if language == "python" else "x <- 1",
            execution_count=1, outputs=[nbformat.v4.new_output("stream", text="private-output-payload")])])) )
    return path


def edited_session(notebook):
    result = prepare(notebook)
    script = Path(result["script"])
    script.write_text(script.read_text().replace("x = 1", "x = 2").replace("x <- 1", "x <- 2"))
    return result


def test_discovery_lists_active_and_closed_sessions_without_outputs(notebook):
    first = prepare(notebook)
    apply(first["session"])
    second = prepare(notebook)
    listing = sessions(notebook)
    assert [item["phase"] for item in listing["sessions"]] == ["prepared", "applied"]
    assert listing["sessions"][0]["session"] == second["session"]
    assert all(item["created_at"] for item in listing["sessions"])
    assert "private-output-payload" not in json.dumps(listing)
    assert len(sessions(notebook.parent.parent)["sessions"]) == 2


def test_resume_keeps_script_and_backup_unchanged(notebook):
    result = edited_session(notebook)
    script = Path(result["script"]).read_bytes()
    notebook_bytes = notebook.read_bytes()
    info = resume(result["session"])
    assert info["can_resume"] is True
    assert notebook.read_bytes() == notebook_bytes
    assert Path(result["script"]).read_bytes() == script
    apply(result["session"])
    with pytest.raises(WorkflowError, match="prepared"):
        resume(result["session"])


def test_review_is_output_free_and_works_when_notebook_changed(notebook):
    result = edited_session(notebook)
    notebook.write_bytes(notebook.read_bytes() + b"\n")
    before = notebook.read_bytes()
    info = review(result["session"])
    assert info["changed"] == [1]
    assert "private-output-payload" not in Path(info["before_script"]).read_text()
    assert "private-output-payload" not in Path(info["script"]).read_text()
    assert info["notebook_matches_session"] is False
    assert notebook.read_bytes() == before
    with pytest.raises(WorkflowError, match="changed after preparation"):
        resume(result["session"])


def test_abort_retains_artifacts_and_permits_fresh_preparation(notebook):
    result = edited_session(notebook)
    notebook.write_bytes(notebook.read_bytes() + b"\n")
    before = notebook.read_bytes()
    script = Path(result["script"]).read_bytes()
    closed = abort(result["session"])
    assert closed["backup_retained"]
    assert Path(result["script"]).read_bytes() == script
    assert (Path(result["session"]) / "original.ipynb").exists()
    assert notebook.read_bytes() == before
    assert status(result["session"])["phase"] == "aborted"
    fresh = prepare(notebook)
    assert fresh["session"] != result["session"]
    with pytest.raises(WorkflowError, match="aborted"):
        apply(result["session"])


def test_custom_session_root_and_malformed_manifest(notebook, tmp_path):
    root = tmp_path / "custom"
    result = prepare(notebook, session_root=root)
    bad = root / "broken"
    bad.mkdir()
    (bad / "session.json").write_text("not JSON")
    listing = sessions(notebook, session_root=root)
    assert listing["sessions"][0]["session"] == result["session"]
    assert len(listing["errors"]) == 1
    assert sessions(notebook)["sessions"] == []


def test_refresh_only_accepts_the_saved_result_and_restored_status(notebook):
    result = edited_session(notebook)
    with pytest.raises(WorkflowError, match="applied or restored"):
        refresh_state(result["session"])
    apply(result["session"])
    assert refresh_state(result["session"])["outputs_cleared"] == [1]
    assert status(result["session"])["notebook_matches_session"] is True
    restore(result["session"])
    assert refresh_state(result["session"])["outputs_cleared"] == []
    assert status(result["session"])["notebook_matches_session"] is True
    notebook.write_bytes(notebook.read_bytes() + b"\n")
    with pytest.raises(WorkflowError, match="newer changes"):
        refresh_state(result["session"])


def test_status_reports_missing_notebook_and_cli_recovery(notebook, capsys):
    result = prepare(notebook)
    assert main(["sessions", str(notebook)]) == 0
    assert len(json.loads(capsys.readouterr().out)["sessions"]) == 1
    assert main(["review", result["session"]]) == 0
    assert "before_script" in json.loads(capsys.readouterr().out)
    assert main(["resume", result["session"], "--editor", "off"]) == 0
    assert json.loads(capsys.readouterr().out)["can_resume"]
    notebook.unlink()
    assert status(result["session"])["notebook_exists"] is False
    assert main(["abort", result["session"]]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "aborted"


def test_review_never_overwrites_script_named_before(notebook):
    notebook = notebook.rename(notebook.with_name("before.ipynb"))
    result = edited_session(notebook)
    before = Path(result["script"]).read_bytes()
    info = review(result["session"])
    assert info["before_script"] != result["script"]
    assert Path(result["script"]).read_bytes() == before


def test_visible_sessions_and_legacy_recovery(notebook):
    result = prepare(notebook)
    visible = notebook.parent / "notebook-workflow-sessions"
    assert Path(result["session"]).parent == visible
    legacy = visible.rename(notebook.parent / ".notebook-workflow")
    old_session = legacy / Path(result["session"]).name
    assert sessions(notebook)["sessions"][0]["session"] == str(old_session)
    assert sessions(notebook.parent.parent)["sessions"][0]["session"] == str(old_session)
    with pytest.raises(WorkflowError, match="already active"):
        prepare(notebook)
    abort(old_session)
    fresh = prepare(notebook)
    assert Path(fresh["session"]).parent == visible
    assert len(sessions(notebook)["sessions"]) == 2
