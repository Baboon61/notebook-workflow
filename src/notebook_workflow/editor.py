"""Optional authenticated loopback bridge to the local VS Code extension.

Only compact control messages cross the bridge; notebook outputs never reach
the CLI. The extension owns saving and refreshing its open notebook document.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from .core import WorkflowError


def registry_directory() -> Path:
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    return Path(tempfile.gettempdir()) / ("notebook-workflow-bridges-" + user)


def _request(descriptor: Path, operation: str, notebook: str, **extra) -> dict:
    settings = json.loads(descriptor.read_text())
    port = settings["port"]
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise WorkflowError("Invalid editor bridge port.")
    payload = json.dumps({"operation": operation, "notebook": notebook, **extra}).encode()
    request = Request(f"http://127.0.0.1:{port}/workflow", data=payload,
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + settings["token"]})
    # Never send a local control token through HTTP_PROXY.
    with build_opener(ProxyHandler({})).open(request, timeout=20) as response:
        result = json.loads(response.read(65536))
    if result.get("error"):
        raise WorkflowError(result["error"])
    return result


def find_editor(notebook: str) -> Path | None:
    matches = []
    for descriptor in registry_directory().glob("*.json"):
        try:
            result = _request(descriptor, "inspect", notebook)
        except (OSError, URLError, ValueError, KeyError):
            continue  # Closed/stale windows must not prevent normal CLI use.
        if result.get("handled"):
            matches.append(descriptor)
    if len(matches) > 1:
        raise WorkflowError("This notebook is open in multiple VS Code windows. Close the duplicate before assistance.")
    return matches[0] if matches else None


def before_prepare(notebook: str, mode: str) -> Path | None:
    if mode == "off":
        return None
    descriptor = find_editor(notebook)
    if descriptor is None:
        if mode == "required":
            raise WorkflowError("No VS Code bridge owns this open notebook. Open it and enable the Notebook Workflow extension.")
        return None
    result = _request(descriptor, "save", notebook)
    if not result.get("handled"):
        raise WorkflowError("The notebook closed before VS Code saved it; retry preparation.")
    return descriptor


def record_editor(session: str, descriptor: Path | None) -> None:
    if descriptor is not None:
        (Path(session) / "editor.json").write_text(json.dumps({"descriptor": str(descriptor)}) + "\n")


def before_apply(session: str, mode: str) -> Path | None:
    if mode == "off":
        return None
    folder = Path(session)
    notebook = json.loads((folder / "session.json").read_text())["notebook"]
    connection = folder / "editor.json"
    if connection.exists():
        descriptor = Path(json.loads(connection.read_text())["descriptor"])
        try:
            result = _request(descriptor, "check", notebook)
        except WorkflowError:
            raise
        except (OSError, URLError, ValueError, KeyError) as error:
            # A VS Code reload starts a new endpoint. Rebind only to a unique
            # open, clean document; never fall back to an unchecked file write.
            replacement = find_editor(notebook)
            if replacement is None:
                raise WorkflowError("The connected VS Code bridge is unavailable. Reopen the notebook in VS Code before continuing.") from error
            result = _request(replacement, "check", notebook)
            if not result.get("handled"):
                raise WorkflowError("The notebook closed during editor reconnection.")
            record_editor(str(folder), replacement)
            return replacement
        # The window is still connected but the document was closed: file hash
        # checks can safely handle it. A dirty open document always fails.
        if result.get("handled"):
            # Even a still-live original window must not mask duplicate owners.
            owner = find_editor(notebook)
            if owner is not None and owner != descriptor:
                raise WorkflowError("Editor ownership changed during the operation; retry after closing duplicate windows.")
            _request(descriptor, "check", notebook)
            return descriptor
        replacement = find_editor(notebook)
        if replacement is not None:
            _request(replacement, "check", notebook)
            record_editor(str(folder), replacement)
            return replacement
        if mode == "required":
            raise WorkflowError("Open the session notebook in VS Code before continuing.")
        return None
    descriptor = find_editor(notebook)
    if descriptor is None:
        if mode == "required":
            raise WorkflowError("No connected editor for this session; open the notebook in VS Code first.")
        return None
    _request(descriptor, "check", notebook)
    return descriptor


def after_apply(descriptor: Path | None, summary: dict) -> dict:
    if descriptor is None:
        return {"connected": False, "refreshed": False}
    try:
        result = _request(descriptor, "refresh", summary["notebook"],
                          outputs_cleared=summary["outputs_cleared"])
        return {"connected": True, "refreshed": result.get("refreshed", False),
                "open": result.get("handled", False)}
    except (OSError, URLError, ValueError, KeyError) as error:
        # The file was already applied. Report a refresh failure separately so
        # neither the user nor the assistant retries mutation on a closed session.
        return {"connected": True, "refreshed": False, "error": str(error),
                "action": "Notebook changes are saved. Retry refresh for this session, or reopen without saving a stale editor buffer."}
