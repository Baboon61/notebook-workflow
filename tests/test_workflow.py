"""Observable round-trip invariants; no Python/R analysis is executed."""

import json
from pathlib import Path

import jupytext
import nbformat
import pytest

from notebook_workflow import WorkflowError, apply, prepare, restore, status
from notebook_workflow.cli import main
from notebook_workflow.core import LABEL, detect_language


@pytest.fixture(params=["python", "r"])
def notebook(tmp_path, request):
    language = request.param
    code = "x = 1" if language == "python" else "x <- 1"
    kernel = {"name": "python3" if language == "python" else "ir",
              "display_name": "Python 3" if language == "python" else "R",
              "language": language}
    nb = nbformat.v4.new_notebook(metadata={"kernelspec": kernel,
        "custom": {"keep": True}, "widgets": {"state": "large-widget-payload"}}, cells=[
        nbformat.v4.new_markdown_cell("# Analysis\n\n![image](attachment:plot.png)",
            metadata={"tags": ["intro"]}, attachments={"plot.png": {"image/png": "image-payload"}}),
        nbformat.v4.new_code_cell(code, execution_count=4, metadata={
            "tags": ["parameters"], "execution": {"iopub.status.busy": "previous-time"}},
            outputs=[nbformat.v4.new_output("display_data", data={
                "text/plain": "original-result", "image/png": "large-plot-payload"})]),
        nbformat.v4.new_code_cell("print(x)", execution_count=5,
            outputs=[nbformat.v4.new_output("stream", text="1\n")]),
        nbformat.v4.new_raw_cell("Raw narrative", metadata={"format": "text/plain"}),
    ])
    path = tmp_path / "analysis.ipynb"
    path.write_text(json.dumps(nb, indent=2) + "\n")
    return path


def document(path):
    return json.loads(path.read_text())


def edit_session(result, edit):
    path = Path(result["script"])
    fmt = "py:percent" if result["language"] == "python" else "R:percent"
    nb = jupytext.reads(path.read_text(), fmt=fmt)
    edit(nb)
    path.write_text(jupytext.writes(nb, fmt=fmt))


def test_noop_preserves_notebook_bytes_and_existing_pair(notebook):
    before = notebook.read_bytes()
    sibling = notebook.with_suffix(".py" if detect_language(document(notebook)["metadata"]) == "python" else ".R")
    sibling.write_text("Existing script must not be overwritten\n")
    session = prepare(notebook)
    text = Path(session["script"]).read_text()
    assert all(payload not in text for payload in (
        "large-widget-payload", "large-plot-payload", "image-payload", "original-result"))
    assert notebook.read_bytes() == before
    summary = apply(session["session"])
    assert summary["notebook_changed"] is False
    assert notebook.read_bytes() == before
    assert sibling.read_text() == "Existing script must not be overwritten\n"


def test_one_edit_clears_changed_cell_and_its_consumer(notebook):
    before = document(notebook)
    session = prepare(notebook)
    edit_session(session, lambda nb: setattr(nb.cells[1], "source", nb.cells[1].source.replace("1", "2")))
    preview = apply(session["session"], dry_run=True)
    assert preview["changed"] == [2]
    assert document(notebook) == before
    summary = apply(session["session"])
    after = document(notebook)
    assert summary["outputs_cleared"] == [2, 3]
    assert summary["dependents_cleared"] == [3]
    assert after["metadata"] == before["metadata"]
    assert after["cells"][0] == before["cells"][0]
    assert after["cells"][3:] == before["cells"][3:]
    assert after["cells"][2]["source"] == before["cells"][2]["source"]
    assert after["cells"][2]["outputs"] == [] and after["cells"][2]["execution_count"] is None
    changed = after["cells"][1]
    assert changed["id"] == before["cells"][1]["id"]
    assert changed["metadata"] == {"tags": ["parameters"]}
    assert changed["outputs"] == [] and changed["execution_count"] is None
    assert LABEL not in changed["metadata"]


def test_markdown_edit_keeps_attachments_and_all_code_outputs(notebook):
    before = document(notebook)
    session = prepare(notebook)
    edit_session(session, lambda nb: setattr(nb.cells[0], "source", nb.cells[0].source + "\nNew note"))
    summary = apply(session["session"])
    after = document(notebook)
    assert summary["outputs_cleared"] == []
    assert after["cells"][0]["attachments"] == before["cells"][0]["attachments"]
    assert after["cells"][1:] == before["cells"][1:]


def test_add_delete_reorder_preserves_sources_and_invalidates_changed_order(notebook):
    before = document(notebook)
    session = prepare(notebook)
    def edit(nb):
        nb.cells = [nb.cells[2], nbformat.v4.new_code_cell("print('new')"), nb.cells[1], nb.cells[0]]
    edit_session(session, edit)
    summary = apply(session["session"])
    after = document(notebook)
    assert summary["changed"] == []
    assert summary["deleted"] == [4] and summary["added"] == [2]
    for new_index, old_index in ((0, 2), (2, 1)):
        assert after["cells"][new_index]["source"] == before["cells"][old_index]["source"]
        assert after["cells"][new_index]["id"] == before["cells"][old_index]["id"]
        assert after["cells"][new_index]["outputs"] == []
        assert after["cells"][new_index]["execution_count"] is None
    assert after["cells"][3] == before["cells"][0]
    assert after["cells"][1]["outputs"] == []
    assert len({cell["id"] for cell in after["cells"]}) == 4


def test_cell_type_change_removes_incompatible_fields(notebook):
    session = prepare(notebook)
    def edit(nb):
        nb.cells[1]["cell_type"] = "markdown"
        nb.cells[1]["source"] = "Explanation instead of code"
        nb.cells[1].pop("outputs")
        nb.cells[1].pop("execution_count")
    edit_session(session, edit)
    apply(session["session"])
    cell = document(notebook)["cells"][1]
    assert cell["cell_type"] == "markdown"
    assert "outputs" not in cell and "execution_count" not in cell


def test_changed_notebook_is_never_overwritten(notebook):
    session = prepare(notebook)
    notebook.write_bytes(notebook.read_bytes() + b"\n")
    changed = notebook.read_bytes()
    with pytest.raises(WorkflowError, match="changed during AI work"):
        apply(session["session"])
    assert notebook.read_bytes() == changed


@pytest.mark.parametrize("damage", ["duplicate", "unknown", "missing"])
def test_damaged_cell_labels_fail_without_writing(notebook, damage):
    session = prepare(notebook)
    def edit(nb):
        if damage == "duplicate":
            nb.cells[1].metadata[LABEL] = nb.cells[0].metadata[LABEL]
        elif damage == "unknown":
            nb.cells[1].metadata[LABEL] = "invented"
        else:
            nb.cells[1].metadata.pop(LABEL)
    edit_session(session, edit)
    before = notebook.read_bytes()
    with pytest.raises(WorkflowError):
        apply(session["session"])
    assert notebook.read_bytes() == before


def test_restore_is_exact_and_refuses_newer_changes(notebook):
    before = notebook.read_bytes()
    session = prepare(notebook)
    edit_session(session, lambda nb: setattr(nb.cells[1], "source", "print('edit')"))
    apply(session["session"])
    restored = restore(session["session"])
    assert restored["phase"] == "restored"
    assert notebook.read_bytes() == before
    session = prepare(notebook)
    apply(session["session"])
    notebook.write_bytes(before + b"\n")
    with pytest.raises(WorkflowError, match="newer changes"):
        restore(session["session"])


def test_double_prepare_and_double_apply_refused(notebook):
    session = prepare(notebook)
    with pytest.raises(WorkflowError, match="already active"):
        prepare(notebook)
    apply(session["session"])
    with pytest.raises(WorkflowError, match="applied"):
        apply(session["session"])
    assert status(session["session"])["phase"] == "applied"


def test_backup_and_baseline_damage_refused(notebook):
    session = prepare(notebook)
    folder = Path(session["session"])
    backup = folder / "original.ipynb"
    before = backup.read_bytes()
    backup.write_bytes(before + b"\n")
    with pytest.raises(WorkflowError, match="backup changed"):
        apply(folder)
    backup.write_bytes(before)
    (folder / "baseline.json").write_text("[]")
    with pytest.raises(WorkflowError, match="baseline"):
        apply(folder)


def test_script_header_cannot_overwrite_notebook_metadata(notebook):
    before = document(notebook)["metadata"]
    session = prepare(notebook)
    def edit(nb):
        nb.metadata["kernelspec"]["display_name"] = "AI changed header"
        nb.cells[1].source = "print('edit')"
    edit_session(session, edit)
    apply(session["session"])
    assert document(notebook)["metadata"] == before


def test_older_notebook_missing_ids_and_list_sources_preserved(notebook):
    nb = document(notebook)
    nb["nbformat_minor"] = 4
    for cell in nb["cells"]:
        cell.pop("id")
        cell["source"] = cell["source"].splitlines(keepends=True)
    notebook.write_text(json.dumps(nb))
    session = prepare(notebook)
    edit_session(session, lambda doc: setattr(doc.cells[1], "source", "print('edit')"))
    apply(session["session"])
    after = document(notebook)
    assert after["cells"][0] == nb["cells"][0]
    assert after["cells"][2]["source"] == nb["cells"][2]["source"]
    assert after["cells"][2]["outputs"] == [] and after["cells"][2]["execution_count"] is None
    assert after["cells"][3:] == nb["cells"][3:]
    assert after["nbformat_minor"] == 4


def test_language_detection_and_unknown_kernel(tmp_path):
    assert detect_language({"kernelspec": {"language": "R", "display_name": "R with Python"}}) == "r"
    assert detect_language({"kernelspec": {"name": "python3"}}) == "python"
    notebook = tmp_path / "unknown.ipynb"
    notebook.write_text(json.dumps(nbformat.v4.new_notebook()))
    with pytest.raises(WorkflowError, match="Unknown kernel"):
        prepare(notebook)


def test_literal_cell_markers_do_not_split_notebook_cells(notebook):
    nb = document(notebook)
    nb["cells"][1]["source"] = '# %%\n# %% literal marker\n# <codecell>\n# In[1]:\n# notebook-workflow-literal "original"\nx = 1'
    notebook.write_text(json.dumps(nb))
    session = prepare(notebook)
    assert session["cells"] == 4
    assert apply(session["session"])["notebook_changed"] is False


def test_duplicate_cell_with_new_boundary_gets_new_id(notebook):
    before = document(notebook)
    session = prepare(notebook)
    def edit(nb):
        nb.cells.append(nbformat.v4.new_code_cell(nb.cells[1].source))
    edit_session(session, edit)
    summary = apply(session["session"])
    after = document(notebook)
    assert summary["added"] == [5]
    assert after["cells"][:4] == before["cells"]
    assert after["cells"][4]["id"] != before["cells"][1]["id"]


def test_empty_notebook_can_add_first_cell(tmp_path):
    path = tmp_path / "empty.ipynb"
    path.write_text(json.dumps(nbformat.v4.new_notebook(metadata={
        "kernelspec": {"name": "python3", "language": "python", "display_name": "Python"}})))
    session = prepare(path)
    edit_session(session, lambda nb: nb.cells.append(nbformat.v4.new_code_cell("x = 1")))
    assert apply(session["session"])["added"] == [1]


def test_lost_identity_for_modified_cell_refused_when_all_labels_removed(notebook):
    session = prepare(notebook)
    def edit(nb):
        for cell in nb.cells:
            cell.metadata.pop(LABEL)
        nb.cells[1].source = "print('edit')"
    edit_session(session, edit)
    with pytest.raises(WorkflowError, match="lost its workflow_id"):
        apply(session["session"])


def test_all_cells_can_be_deleted(notebook):
    session = prepare(notebook)
    edit_session(session, lambda nb: setattr(nb, "cells", []))
    summary = apply(session["session"])
    assert summary["deleted"] == [1, 2, 3, 4]
    assert document(notebook)["cells"] == []


@pytest.mark.parametrize("fixture", ["python_kernel_with_r_magic", "r_kernel_with_reticulate"])
def test_cross_language_fixtures_roundtrip(tmp_path, fixture):
    path = tmp_path / (fixture + ".ipynb")
    python = fixture.startswith("python")
    kernel = {"name": "python3" if python else "ir", "language": "python" if python else "R",
              "display_name": "Python 3" if python else "R"}
    source = "%%R\nx <- 1" if python else 'reticulate::py_run_string("x = 1")\n'
    path.write_text(json.dumps(nbformat.v4.new_notebook(metadata={"kernelspec": kernel},
        cells=[nbformat.v4.new_code_cell(source)])))
    before = path.read_bytes()
    session = prepare(path)
    assert apply(session["session"])["notebook_changed"] is False
    assert path.read_bytes() == before


def test_cli_returns_compact_summaries(notebook, capsys):
    assert main(["prepare", str(notebook)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["language"] in {"python", "r"}
    assert main(["apply", output["session"], "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["notebook_changed"] is False
    assert main(["apply", output["session"]]) == 0
    capsys.readouterr()
    assert main(["apply", output["session"]]) == 1
    assert "applied" in json.loads(capsys.readouterr().err)["error"]
