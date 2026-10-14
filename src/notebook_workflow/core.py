"""Jupytext transport with cell-level merging and exact notebook backups.

Notebook JSON is handled only by this deterministic tool. AI workers see the
percent script and compact summaries, never the backup or notebook outputs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jupytext
import nbformat

from .dependencies import invalidation


LABEL = "workflow_id"
SCHEMA = 1
SESSION_DIRECTORY = "notebook-workflow-sessions"
LEGACY_SESSION_DIRECTORY = ".notebook-workflow"
ESCAPE = "# notebook-workflow-literal "
MARKER = re.compile(r"^\s*#\s*(?:%%(?:\s|$)|<codecell>\s*$|In\[[0-9 ]*\]:?\s*$)")


class WorkflowError(ValueError):
    """An unsafe or unsupported editing session."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _escape_source(source: str) -> str:
    # Literal percent markers inside a notebook cell must not create extra
    # cells when Jupytext reads the script. Preserve them as encoded comments.
    return "\n".join(ESCAPE + json.dumps(line) if MARKER.match(line) or line.startswith(ESCAPE)
                     else line for line in source.split("\n"))


def _unescape_source(source: str) -> str:
    lines = []
    for line in source.split("\n"):
        if line.startswith(ESCAPE):
            decoded = json.loads(line[len(ESCAPE):])
            if not isinstance(decoded, str):
                raise WorkflowError("Invalid encoded literal cell marker.")
            line = decoded
        lines.append(line)
    return "\n".join(lines)


def detect_language(metadata: dict) -> str:
    """Prefer explicit kernel language over incidental display-name text."""
    kernel = metadata.get("kernelspec") or {}
    info = metadata.get("language_info") or {}
    for value in (kernel.get("language"), info.get("name"), kernel.get("name"), kernel.get("display_name")):
        value = str(value or "").strip().lower()
        if value in {"python", "python3"} or value.startswith("python "):
            return "python"
        if value in {"r", "ir", "irkernel"} or value.startswith("r "):
            return "r"
    raise WorkflowError("Unknown kernel language. Select a Python or R kernel and save the notebook first.")


def _read_notebook(data: bytes) -> dict:
    notebook = json.loads(data)
    if notebook.get("nbformat") != 4:
        raise WorkflowError("Only notebook format 4 is supported; convert older notebooks in Jupyter first.")
    return notebook


def _atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    """Replace through a same-directory temporary file; preserve file permissions."""
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_state(folder: Path, state: dict) -> None:
    _atomic_write(folder / "session.json", json.dumps(state, indent=2).encode() + b"\n")


def _load_state(folder: str | Path) -> tuple[Path, dict]:
    folder = Path(folder).resolve()
    state = json.loads((folder / "session.json").read_text())
    if state.get("schema") != SCHEMA:
        raise WorkflowError("Unsupported editing-session version.")
    # Filenames in the manifest may not escape the session directory.
    for key in ("script", "backup", "baseline"):
        if Path(state[key]).name != state[key]:
            raise WorkflowError("Invalid session filename.")
    return folder, state


def _backup(folder: Path, state: dict) -> tuple[bytes, dict]:
    data = (folder / state["backup"]).read_bytes()
    if _digest(data) != state["original_hash"]:
        raise WorkflowError("The original backup changed; refusing to apply or restore.")
    return data, _read_notebook(data)


def _transport(notebook: dict, language: str, labels: list[str]) -> str:
    cells = []
    for cell, label in zip(notebook["cells"], labels):
        # Carry identity only. Outputs, attachments, and arbitrary notebook/cell
        # metadata stay in the backup and cannot inflate the AI representation.
        cells.append(nbformat.from_dict({
            "cell_type": cell["cell_type"],
            "source": _escape_source(_source(cell)) if cell["cell_type"] == "code" else _source(cell),
            "metadata": {LABEL: label}, "id": label,
            **({"outputs": [], "execution_count": None} if cell["cell_type"] == "code" else {}),
        }))
    metadata = {key: copy.deepcopy(notebook.get("metadata", {})[key])
                for key in ("kernelspec", "language_info") if key in notebook.get("metadata", {})}
    metadata["jupytext"] = {
        "notebook_metadata_filter": "kernelspec,language_info",
        "cell_metadata_filter": LABEL,
    }
    document = nbformat.v4.new_notebook(cells=cells, metadata=metadata)
    return jupytext.writes(document, fmt="py:percent" if language == "python" else "R:percent")


def _parse(script: str, language: str) -> list[dict]:
    document = jupytext.reads(script, fmt="py:percent" if language == "python" else "R:percent")
    return [{"label": cell.metadata.get(LABEL), "cell_type": cell.cell_type,
             "source": _unescape_source(cell.source) if cell.cell_type == "code" else cell.source}
            for cell in document.cells]


def prepare(notebook: str | Path, *, session_root: str | Path | None = None,
            dependency_policy: str = "conservative") -> dict:
    """Export a saved notebook, without modifying it or existing paired scripts."""
    notebook = Path(notebook).resolve()
    if notebook.suffix != ".ipynb":
        raise WorkflowError("prepare requires a saved .ipynb file.")
    data = notebook.read_bytes()
    original = _read_notebook(data)
    language = detect_language(original.get("metadata", {}))
    if dependency_policy not in {"conservative", "identified", "changed-only"}:
        raise WorkflowError("Unknown dependency policy.")
    root = Path(session_root).resolve() if session_root else notebook.parent / SESSION_DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    for existing in sessions(notebook, session_root=root)["sessions"] + sessions(notebook)["sessions"]:
        if existing["phase"] == "prepared":
            raise WorkflowError(f"An editing session is already active: {existing['session']}")
    labels = ["cell-" + uuid.uuid4().hex for _ in original["cells"]]
    script = _transport(original, language, labels)
    baseline = _parse(script, language)
    # Validate the transport before it can be used to rewrite a notebook. Some
    # unusual cell contents are not lossless in percent format.
    if len(baseline) != len(original["cells"]) or any(
        item["label"] != label or item["cell_type"] != cell["cell_type"]
        or item["source"].rstrip("\n") != _source(cell).rstrip("\n")
        for item, label, cell in zip(baseline, labels, original["cells"])
    ):
        raise WorkflowError("This notebook does not round-trip losslessly through Jupytext percent format.")
    folder = root / (notebook.stem + "-" + uuid.uuid4().hex[:12])
    folder.mkdir(mode=0o700)
    state = {
        "schema": SCHEMA, "phase": "prepared", "notebook": str(notebook),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "language": language, "script": notebook.stem + (".py" if language == "python" else ".R"),
        "backup": "original.ipynb", "baseline": "baseline.json",
        "original_hash": _digest(data), "cell_labels": labels,
        "dependency_policy": dependency_policy,
    }
    (folder / state["backup"]).write_bytes(data)
    (folder / state["baseline"]).write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    (folder / state["script"]).write_text(script)
    _save_state(folder, state)
    return {"session": str(folder), "notebook": str(notebook), "language": language,
            "dependency_policy": dependency_policy,
            "script": str(folder / state["script"]), "cells": len(labels), "phase": "prepared"}


def _merge(folder: Path, state: dict, original: dict) -> tuple[dict, dict]:
    baseline = json.loads((folder / state["baseline"]).read_text())
    labels = state["cell_labels"]
    # Baseline integrity is checked against a freshly generated representation
    # of the backup rather than trusting an editable manifest of cell sources.
    expected = _parse(_transport(original, state["language"], labels), state["language"])
    if baseline != expected or len(labels) != len(original["cells"]) or len(set(labels)) != len(labels):
        raise WorkflowError("The session baseline or cell mapping changed.")
    edited = _parse((folder / state["script"]).read_text(), state["language"])
    edited_labels = {item["label"] for item in edited if item["label"] is not None}
    previous = {item["label"]: (index, item, cell)
                for index, (item, cell) in enumerate(zip(baseline, original["cells"]))}
    seen = set()
    result = copy.deepcopy(original)
    result["cells"] = []
    summary = {"changed": [], "added": [], "deleted": [], "moved": [], "outputs_cleared": []}
    used_ids = {cell["id"] for cell in original["cells"] if "id" in cell}
    for index, item in enumerate(edited):
        label = item["label"]
        if label is not None:
            if label not in previous:
                raise WorkflowError(f"Unknown cell label {label!r}; omit workflow_id on new cells.")
            if label in seen:
                raise WorkflowError(f"Duplicate cell label {label!r}; omit workflow_id when copying a cell.")
            seen.add(label)
            old_index, before, cell = previous[label]
            cell = copy.deepcopy(cell)
            changed = item["source"] != before["source"] or item["cell_type"] != before["cell_type"]
            if old_index != index:
                summary["moved"].append(index + 1)
            if changed:
                summary["changed"].append(index + 1)
                cell["source"] = item["source"]
                cell["cell_type"] = item["cell_type"]
                if item["cell_type"] == "code":
                    cell.pop("attachments", None)
                    cell["outputs"] = []
                    cell["execution_count"] = None
                    cell.get("metadata", {}).pop("execution", None)
                    summary["outputs_cleared"].append(index + 1)
                else:
                    cell.pop("outputs", None)
                    cell.pop("execution_count", None)
                    if item["cell_type"] != "markdown":
                        cell.pop("attachments", None)
        else:
            # A missing label on an existing unchanged cell is usually a damaged
            # boundary, not an intentional delete-and-add operation.
            if any(before["label"] not in edited_labels and item["cell_type"] == before["cell_type"]
                   and item["source"] == before["source"] for _, before, _ in previous.values()):
                raise WorkflowError("A cell lost its workflow_id. Restore the existing cell label.")
            cell = {"cell_type": item["cell_type"], "source": item["source"], "metadata": {}}
            if original.get("nbformat_minor", 0) >= 5:
                new_id = uuid.uuid4().hex[:12]
                while new_id in used_ids:
                    new_id = uuid.uuid4().hex[:12]
                used_ids.add(new_id)
                cell["id"] = new_id
            if item["cell_type"] == "code":
                cell.update(outputs=[], execution_count=None)
                summary["outputs_cleared"].append(index + 1)
            summary["added"].append(index + 1)
        result["cells"].append(cell)
    summary["deleted"] = [index + 1 for index, label in enumerate(labels) if label not in seen]
    summary["unchanged"] = len(edited) - len(summary["changed"]) - len(summary["added"])
    affected, details = invalidation(baseline, edited, state["language"],
                                    state.get("dependency_policy", "conservative"))
    summary.update(details)
    summary["dependents_cleared"] = [number for number in affected
                                     if number not in summary["changed"] + summary["added"]]
    for number in affected:
        cell = result["cells"][number - 1]
        cell["outputs"] = []
        cell["execution_count"] = None
        cell.get("metadata", {}).pop("execution", None)
    summary["outputs_cleared"] = sorted(set(summary["outputs_cleared"] + affected))
    return result, summary


def apply(session: str | Path, *, dry_run: bool = False) -> dict:
    """Merge script edits; fail if the saved notebook changed during AI work."""
    folder, state = _load_state(session)
    if state["phase"] != "prepared":
        raise WorkflowError(f"Session is {state['phase']}; prepare a new session for further edits.")
    original_data, original = _backup(folder, state)
    notebook = Path(state["notebook"])
    if _digest(notebook.read_bytes()) != state["original_hash"]:
        raise WorkflowError("The saved notebook changed during AI work. No changes applied; reconcile before preparing again.")
    merged, summary = _merge(folder, state, original)
    # Existing notebook-level metadata is authoritative, even if the script's
    # YAML header is edited. Unchanged cells are copied without normalization.
    summary.update(session=str(folder), notebook=str(notebook), dry_run=dry_run)
    changed = merged != original
    summary["notebook_changed"] = changed
    if dry_run:
        return summary
    output = original_data
    if changed:
        output = json.dumps(merged, ensure_ascii=False, indent=1).encode() + b"\n"
        mode = stat.S_IMODE(notebook.stat().st_mode)
        # Check immediately before the atomic replacement too.
        if _digest(notebook.read_bytes()) != state["original_hash"]:
            raise WorkflowError("The notebook changed before writing. No changes applied.")
        _atomic_write(notebook, output, mode)
    state.update(phase="applied", applied_hash=_digest(output), summary=summary,
                 finished_at=datetime.now(timezone.utc).isoformat())
    _save_state(folder, state)
    return summary


def restore(session: str | Path) -> dict:
    """Restore the exact backup, only if no later notebook edits would be lost."""
    folder, state = _load_state(session)
    if state["phase"] not in {"prepared", "applied"}:
        raise WorkflowError(f"Session is already {state['phase']}.")
    data, _ = _backup(folder, state)
    notebook = Path(state["notebook"])
    expected = state.get("applied_hash", state["original_hash"])
    if _digest(notebook.read_bytes()) != expected:
        raise WorkflowError("The notebook has newer changes. Restore refused to avoid losing them.")
    if notebook.read_bytes() != data:
        _atomic_write(notebook, data, stat.S_IMODE(notebook.stat().st_mode))
    state["phase"] = "restored"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(folder, state)
    return {"session": str(folder), "notebook": str(notebook), "phase": "restored"}


def status(session: str | Path) -> dict:
    folder, state = _load_state(session)
    notebook = Path(state["notebook"])
    current = _digest(notebook.read_bytes()) if notebook.exists() else None
    expected = state["applied_hash"] if state["phase"] == "applied" else state["original_hash"]
    return {"session": str(folder), "notebook": state["notebook"], "language": state["language"],
            "script": str(folder / state["script"]), "phase": state["phase"],
            "created_at": state.get("created_at"), "finished_at": state.get("finished_at"),
            "dependency_policy": state.get("dependency_policy", "conservative"),
            "notebook_exists": current is not None,
            "notebook_changed_since_prepare": current != state["original_hash"],
            "notebook_matches_session": current == expected,
            "can_resume": state["phase"] == "prepared" and current == state["original_hash"]}


def sessions(path: str | Path, *, session_root: str | Path | None = None) -> dict:
    """Discover session manifests, without opening notebooks or backups.

    A notebook reference looks in its own default session directory. A project
    directory searches for named visible and legacy session directories. Custom roots
    are searched only when supplied explicitly.
    """
    path = Path(path).resolve()
    notebook = path if path.suffix == ".ipynb" else None
    if session_root is not None:
        roots = [Path(session_root).resolve()]
    elif notebook is not None:
        roots = [notebook.parent / SESSION_DIRECTORY, notebook.parent / LEGACY_SESSION_DIRECTORY]
    elif path.name in {SESSION_DIRECTORY, LEGACY_SESSION_DIRECTORY}:
        roots = [path]
    else:
        roots = [folder for name in (SESSION_DIRECTORY, LEGACY_SESSION_DIRECTORY) for folder in path.rglob(name)
                 if not set(folder.relative_to(path).parts).intersection({".git", ".venv", "node_modules"})]
    records, errors = [], []
    for root in roots:
        for manifest in sorted(root.glob("*/session.json")):
            try:
                folder, state = _load_state(manifest.parent)
                if notebook is not None and Path(state["notebook"]).resolve() != notebook:
                    continue
                records.append({"session": str(folder), "notebook": state["notebook"],
                    "script": str(folder / state["script"]), "phase": state["phase"],
                    "language": state["language"], "created_at": state.get("created_at"),
                    "finished_at": state.get("finished_at")})
            except (OSError, ValueError, KeyError) as error:
                errors.append({"session": str(manifest.parent), "error": str(error)})
    records.sort(key=lambda item: (item["created_at"] or "", item["session"]), reverse=True)
    return {"sessions": records, "errors": errors}


def review(session: str | Path) -> dict:
    """Write an output-free baseline script for editor diff, with a compact summary."""
    folder, state = _load_state(session)
    _, original = _backup(folder, state)
    _, summary = _merge(folder, state, original)
    baseline_script = _transport(original, state["language"], state["cell_labels"])
    filename = "before.py" if state["language"] == "python" else "before.R"
    if filename == state["script"]:
        filename = "baseline-" + filename
    _atomic_write(folder / filename, baseline_script.encode())
    return {**summary, **status(folder), "before_script": str(folder / filename)}


def resume(session: str | Path) -> dict:
    """Validate an interrupted session without exporting over its edited script."""
    folder, state = _load_state(session)
    if state["phase"] != "prepared":
        raise WorkflowError(f"Session is {state['phase']}; only prepared sessions can be resumed.")
    _, original = _backup(folder, state)
    _merge(folder, state, original)
    if _digest(Path(state["notebook"]).read_bytes()) != state["original_hash"]:
        raise WorkflowError("The notebook changed after preparation. Keep both versions, review the script, then abort this session before preparing again.")
    return status(folder)


def abort(session: str | Path) -> dict:
    """Close a prepared session, retaining its script and backup; never alter a notebook."""
    folder, state = _load_state(session)
    if state["phase"] != "prepared":
        raise WorkflowError(f"Session is {state['phase']}; only prepared sessions can be aborted.")
    state.update(phase="aborted", finished_at=datetime.now(timezone.utc).isoformat())
    _save_state(folder, state)
    return {"session": str(folder), "notebook": state["notebook"], "phase": "aborted",
            "script": str(folder / state["script"]), "backup_retained": True}


def refresh_state(session: str | Path) -> dict:
    """Validate the saved result before retrying editor refresh after apply/restore."""
    folder, state = _load_state(session)
    if state["phase"] not in {"applied", "restored"}:
        raise WorkflowError("Editor refresh requires an applied or restored session.")
    expected = state["original_hash"] if state["phase"] == "restored" else state["applied_hash"]
    if _digest(Path(state["notebook"]).read_bytes()) != expected:
        raise WorkflowError("The notebook has newer changes. Session refresh refused; no file was changed.")
    return {"session": str(folder), "notebook": state["notebook"], "phase": state["phase"],
            "outputs_cleared": state.get("summary", {}).get("outputs_cleared", []) if state["phase"] == "applied" else []}
