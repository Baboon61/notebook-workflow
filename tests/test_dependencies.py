"""Source-only dependency tests. No Python or R notebook cells are executed."""

import json
from pathlib import Path

import jupytext
import nbformat
import pytest

from notebook_workflow import apply, prepare, restore


def notebook(tmp_path, codes, language="python"):
    path = tmp_path / "dependencies.ipynb"
    cells = [nbformat.v4.new_code_cell(code, execution_count=index + 1,
             metadata={"tags": ["keep"], "execution": {"timestamp": "old"}},
             outputs=[nbformat.v4.new_output("stream", text=f"output {index + 1}")])
             for index, code in enumerate(codes)]
    path.write_text(json.dumps(nbformat.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"language": language, "name": "python3" if language == "python" else "ir",
                       "display_name": language}, "custom": {"keep": True}})))
    return path


def edit(prepared, change):
    path = Path(prepared["script"])
    fmt = "py:percent" if prepared["language"] == "python" else "R:percent"
    document = jupytext.reads(path.read_text(), fmt=fmt)
    change(document)
    path.write_text(jupytext.writes(document, fmt=fmt))


@pytest.mark.parametrize("language", ["python", "r"])
def test_transitive_dependents_clear_and_independent_plot_is_preserved(tmp_path, language):
    codes = ["value = 2", "value2 = value * 10", "print(value2)", "print('independent plot')"]
    if language == "r":
        codes = [code.replace(" = ", " <- ") for code in codes]
    path = notebook(tmp_path, codes, language)
    before_bytes = path.read_bytes()
    before = json.loads(before_bytes)
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", doc.cells[0].source.replace("2", "3")))
    preview = apply(prepared["session"], dry_run=True)
    assert preview["changed"] == [1]
    assert preview["dependents_cleared"] == [2, 3]
    assert preview["outputs_cleared"] == [1, 2, 3]
    assert preview["dependency_fallback"] == []
    assert path.read_bytes() == before_bytes
    assert apply(prepared["session"])["outputs_cleared"] == preview["outputs_cleared"]
    after = json.loads(path.read_text())
    assert after["metadata"] == before["metadata"]
    assert after["cells"][3] == before["cells"][3]
    for index in (1, 2):
        cell = after["cells"][index]
        assert cell["source"] == before["cells"][index]["source"]
        assert cell["outputs"] == [] and cell["execution_count"] is None
        assert cell["id"] == before["cells"][index]["id"]
        assert cell["metadata"] == {"tags": ["keep"]}
    restore(prepared["session"])
    assert path.read_bytes() == before_bytes


@pytest.mark.parametrize("language", ["python", "r"])
def test_changing_output_label_does_not_change_same_variable_definition(tmp_path, language):
    first = 'value = 3\nprint(f"Value: {value}")' if language == "python" else 'value <- 3\ncat("Value:", value)'
    path = notebook(tmp_path, [first, "print(value)", "print('independent')"], language)
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", doc.cells[0].source.replace("Value:", "Result:")))
    assert apply(prepared["session"])["outputs_cleared"] == [1]


@pytest.mark.parametrize("language", ["python", "r"])
def test_reassignment_to_independent_constant_stops_dependency_chain(tmp_path, language):
    codes = ["value = 2", "value = 99", "print(value)"]
    if language == "r":
        codes = [code.replace(" = ", " <- ") for code in codes]
    path = notebook(tmp_path, codes, language)
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", doc.cells[0].source.replace("2", "3")))
    assert apply(prepared["session"])["outputs_cleared"] == [1]


@pytest.mark.parametrize("language", ["python", "r"])
def test_deleted_definition_still_invalidates_old_dependents(tmp_path, language):
    path = notebook(tmp_path, ["value = 2" if language == "python" else "value <- 2", "print(value)", "print('independent')"], language)
    prepared = prepare(path)
    edit(prepared, lambda doc: doc.cells.pop(0))
    summary = apply(prepared["session"])
    assert summary["deleted"] == [1]
    assert summary["outputs_cleared"] == [1]
    assert summary["dependents_cleared"] == [1]


@pytest.mark.parametrize("language", ["python", "r"])
def test_dynamic_uncertainty_clears_all_later_code_cells(tmp_path, language):
    dynamic = 'exec("other = value")' if language == "python" else 'eval(parse(text="other <- value"))'
    path = notebook(tmp_path, ["value = 2" if language == "python" else "value <- 2",
                             dynamic, "print('independent')"], language)
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", doc.cells[0].source.replace("2", "3")))
    summary = apply(prepared["session"])
    assert summary["outputs_cleared"] == [1, 2, 3]
    assert summary["dependency_fallback"] == [1, 2, 3]
    assert summary["dependency_warnings"]


@pytest.mark.parametrize("language", ["python", "r"])
def test_comments_only_do_not_trigger_dynamic_fallback(tmp_path, language):
    dynamic = 'exec("x = 1")' if language == "python" else 'eval(parse(text="x <- 1"))'
    path = notebook(tmp_path, [dynamic, "print('independent')"], language)
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", doc.cells[0].source + "\n# explanation"))
    summary = apply(prepared["session"])
    assert summary["outputs_cleared"] == [1]
    assert summary["dependency_fallback"] == []


def test_function_reads_resolve_globals_at_call_time(tmp_path):
    path = notebook(tmp_path, ["def derive():\n    return value * 2", "value = 2",
                             "value2 = derive()", "print(value2)", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[1], "source", "value = 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [2, 3, 4]


def test_function_change_invalidates_callers(tmp_path):
    path = notebook(tmp_path, ["def derive(value):\n    return value * 2", "value2 = derive(3)",
                             "print(value2)", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "def derive(value):\n    return value * 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 2, 3]


def test_mutation_invalidates_object_aliases(tmp_path):
    path = notebook(tmp_path, ["items = []", "alias = items", "items.append(2)",
                             "print(alias)", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[2], "source", "items.append(3)"))
    assert apply(prepared["session"])["outputs_cleared"] == [3, 4]


def test_changed_input_propagates_through_mutation_and_alias(tmp_path):
    path = notebook(tmp_path, ["value = 2", "items = []\nalias = items", "items.append(value)",
                             "print(alias)", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value = 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 3, 4]


def test_forward_reference_conservatively_invalidates_earlier_output(tmp_path):
    path = notebook(tmp_path, ["print(value)", "value = 2", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[1], "source", "value = 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 2]


def test_added_definition_invalidates_later_consumers(tmp_path):
    path = notebook(tmp_path, ["value = 2", "print(value)", "print('independent')"])
    prepared = prepare(path)
    edit(prepared, lambda doc: doc.cells.insert(1, nbformat.v4.new_code_cell("value = 3")))
    summary = apply(prepared["session"])
    assert summary["added"] == [2]
    assert summary["outputs_cleared"] == [2, 3]


def test_changed_only_policy_is_explicit_opt_out(tmp_path):
    path = notebook(tmp_path, ["value = 2", "print(value)"])
    prepared = prepare(path, dependency_policy="changed-only")
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value = 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [1]


def test_identified_policy_reports_uncertainty_without_later_fallback(tmp_path):
    path = notebook(tmp_path, ["value = 2", 'exec("other = value")', "print('independent')"])
    prepared = prepare(path, dependency_policy="identified")
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value = 3"))
    summary = apply(prepared["session"])
    assert summary["dependency_warnings"]
    assert summary["dependency_fallback"] == []
    assert summary["outputs_cleared"] == [1]


def test_r_named_argument_is_not_a_variable_redefinition(tmp_path):
    path = notebook(tmp_path, ["value <- 2", "plot(x = value, y = value)", "print(value)"], "r")
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value <- 3"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 2, 3]


def test_r_function_uncertainty_is_conservative(tmp_path):
    path = notebook(tmp_path, ["derive <- function() value * 2", "value <- 2",
                             "value2 <- derive()", "print(value2)", "print('independent')"], "r")
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[1], "source", "value <- 3"))
    summary = apply(prepared["session"])
    assert summary["outputs_cleared"] == [2, 3, 4, 5]
    assert summary["dependency_warnings"]


def test_r_multiline_definition_change_invalidates_consumers(tmp_path):
    path = notebook(tmp_path, ["value <- 2 +\n  10", "print(value)", "print('independent')"], "r")
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value <- 2 +\n  20"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 2]


def test_r_statement_boundary_change_is_semantic(tmp_path):
    path = notebook(tmp_path, ["value <- 2\n+ 10", "print(value)", "print('independent')"], "r")
    prepared = prepare(path)
    edit(prepared, lambda doc: setattr(doc.cells[0], "source", "value <- 2 +\n10"))
    assert apply(prepared["session"])["outputs_cleared"] == [1, 2]
