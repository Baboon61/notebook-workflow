"""Bridge lifecycle integration with compact messages and a fake local editor."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest

from notebook_workflow import WorkflowError, prepare
from notebook_workflow.cli import main
from notebook_workflow import editor


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    requests = []
    replies = {"inspect": {"handled": True}, "save": {"handled": True},
               "check": {"handled": True}, "refresh": {"handled": True, "refreshed": True}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer local-token"
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(message)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(replies[message["operation"]]).encode())
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    registry = tmp_path / "registry"
    registry.mkdir()
    descriptor = registry / "editor.json"
    descriptor.write_text(json.dumps({"port": server.server_port, "token": "local-token"}))
    monkeypatch.setattr(editor, "registry_directory", lambda: registry)
    try:
        yield descriptor, requests, replies
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def notebook(tmp_path):
    path = tmp_path / "test.ipynb"
    path.write_text(json.dumps({"nbformat": 4, "nbformat_minor": 4, "metadata": {
        "kernelspec": {"name": "python3", "language": "python", "display_name": "Python"}},
        "cells": [{"cell_type": "code", "source": "x = 1", "metadata": {},
                   "execution_count": 1, "outputs": []}]}))
    return path


def test_cli_saves_before_prepare_and_refreshes_after_apply(bridge, notebook, capsys):
    descriptor, requests, _ = bridge
    assert main(["prepare", str(notebook)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["editor"]["saved"]
    assert [item["operation"] for item in requests] == ["inspect", "save"]
    assert (Path(result["session"]) / "editor.json").exists()
    script = Path(result["script"])
    script.write_text(script.read_text().replace("x = 1", "x = 2"))
    assert main(["apply", result["session"], "--dry-run"]) == 0
    capsys.readouterr()
    assert requests[-1]["operation"] == "check"
    assert main(["apply", result["session"]]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["editor"]["refreshed"]
    assert requests[-1] == {"operation": "refresh", "notebook": str(notebook), "outputs_cleared": [1]}


def test_dirty_editor_blocks_apply_before_any_file_write(bridge, notebook, capsys):
    _, _, replies = bridge
    assert main(["prepare", str(notebook)]) == 0
    result = json.loads(capsys.readouterr().out)
    replies["check"] = {"error": "The open notebook has unsaved edits."}
    before = notebook.read_bytes()
    assert main(["apply", result["session"]]) == 1
    assert "unsaved" in capsys.readouterr().err
    assert notebook.read_bytes() == before


def test_refresh_failure_reports_already_applied_file(bridge, notebook, capsys):
    _, _, replies = bridge
    assert main(["prepare", str(notebook)]) == 0
    result = json.loads(capsys.readouterr().out)
    replies["refresh"] = {"error": "The notebook became dirty."}
    assert main(["apply", result["session"]]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert "error" in summary["editor"]
    assert "saved" in summary["editor"]["action"]
    assert json.loads((Path(result["session"]) / "session.json").read_text())["phase"] == "applied"


def test_missing_required_editor_and_explicit_cli_only(notebook, tmp_path, monkeypatch):
    monkeypatch.setattr(editor, "registry_directory", lambda: tmp_path / "absent")
    with pytest.raises(WorkflowError, match="No VS Code bridge"):
        editor.before_prepare(str(notebook), "required")
    assert editor.before_prepare(str(notebook), "auto") is None
    assert editor.before_prepare(str(notebook), "off") is None


def test_duplicate_windows_refused(bridge, notebook):
    descriptor, _, _ = bridge
    descriptor.with_name("other-window.json").write_bytes(descriptor.read_bytes())
    with pytest.raises(WorkflowError, match="multiple"):
        editor.find_editor(str(notebook))


def test_disconnected_session_never_silently_falls_back(bridge, notebook):
    descriptor, _, _ = bridge
    result = prepare(notebook)
    editor.record_editor(result["session"], descriptor)
    descriptor.unlink()
    with pytest.raises(WorkflowError, match="unavailable"):
        editor.before_apply(result["session"], "auto")


def test_reload_reconnects_to_unique_clean_editor_without_losing_script(bridge, notebook, capsys):
    descriptor, requests, _ = bridge
    result = prepare(notebook)
    script = Path(result["script"])
    script.write_text(script.read_text().replace("x = 1", "x = 2"))
    before = script.read_bytes()
    editor.record_editor(result["session"], descriptor)
    replacement = descriptor.with_name("reloaded-window.json")
    descriptor.rename(replacement)
    assert main(["resume", result["session"], "--editor", "required"]) == 0
    assert json.loads(capsys.readouterr().out)["editor"]["connected"]
    assert script.read_bytes() == before
    assert json.loads((Path(result["session"]) / "editor.json").read_text())["descriptor"] == str(replacement)
    assert main(["apply", result["session"]]) == 0
    assert json.loads(capsys.readouterr().out)["editor"]["refreshed"]


def test_restore_blocks_dirty_editor_and_refresh_retry_does_not_reapply(bridge, notebook, capsys):
    _, requests, replies = bridge
    assert main(["prepare", str(notebook)]) == 0
    result = json.loads(capsys.readouterr().out)
    script = Path(result["script"])
    script.write_text(script.read_text().replace("x = 1", "x = 2"))
    assert main(["apply", result["session"]]) == 0
    capsys.readouterr()
    before = notebook.read_bytes()
    assert main(["refresh", result["session"]]) == 0
    assert json.loads(capsys.readouterr().out)["editor"]["refreshed"]
    assert notebook.read_bytes() == before
    replies["check"] = {"error": "Open notebook has unsaved edits"}
    assert main(["restore", result["session"]]) == 1
    assert "unsaved" in capsys.readouterr().err
    assert notebook.read_bytes() == before
    replies["check"] = {"handled": True}
    assert main(["restore", result["session"]]) == 0
    restored = json.loads(capsys.readouterr().out)
    assert restored["editor"]["refreshed"]
    assert requests[-1]["outputs_cleared"] == []


def test_reload_dirty_editor_is_not_rebound(bridge, notebook):
    descriptor, _, replies = bridge
    result = prepare(notebook)
    editor.record_editor(result["session"], descriptor)
    replacement = descriptor.with_name("reload.json")
    descriptor.rename(replacement)
    replies["check"] = {"error": "unsaved edits after reload"}
    with pytest.raises(WorkflowError, match="unsaved"):
        editor.before_apply(result["session"], "auto")
    assert json.loads((Path(result["session"]) / "editor.json").read_text())["descriptor"] == str(descriptor)
