#!/usr/bin/env python3
"""Generate real PBMC QC outputs and measure a notebook-refactor edit.

Heavy artifacts stay in notebook-workflow-benchmarks/. The workflow subcommand
records the actual skill launcher commands and their compact responses. Replay
performs the same fixed edit without making a model request.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import jupytext
import nbformat


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "notebook-workflow-benchmarks/pbmc3k"
LAUNCHER = ROOT / "skills/notebook-refactor/scripts/workflow.py"
DATA_URL = "https://exampledata.scverse.org/scanpy/pbmc3k_raw.h5ad"
DATA_SHA256 = "89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def dataset_provenance(output):
    data = output / "data/pbmc3k_raw.h5ad"
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    if digest != DATA_SHA256:
        raise ValueError("The PBMC3k download does not match the recorded SHA-256.")
    return {"loader": "scanpy.datasets.pbmc3k()", "url": DATA_URL,
            "file_sha256": digest, "file_bytes": data.stat().st_size}


def tokenizer(output):
    import tiktoken

    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(output / "tokenizer-cache"))
    return tiktoken.get_encoding("o200k_base")


def execute_notebook(path, output):
    """Use this interpreter via a temporary kernel spec, without global kernel changes."""
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    from nbclient import NotebookClient

    kernels = output / "kernel-specs"
    spec = kernels / "python3"
    spec.mkdir(parents=True, exist_ok=True)
    write_json(spec / "kernel.json", {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "PBMC3k demo", "language": "python",
    })
    manager = KernelManager(kernel_name="python3", connection_file=str(output / "kernel-connection.json"),
                            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]))
    environment = dict(os.environ)
    environment.update({"MPLCONFIGDIR": str(output / "matplotlib-cache"),
                        "MPLBACKEND": "module://matplotlib_inline.backend_inline",
                        "IPYTHONDIR": str(output / "ipython"),
                        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                        "NUMBA_NUM_THREADS": "1"})
    notebook = nbformat.read(path, as_version=4)
    NotebookClient(notebook, km=manager, timeout=120, record_timing=False,
                   resources={"metadata": {"path": str(output)}}).execute(env=environment)
    nbformat.write(notebook, path)
    return notebook


def qc_summary(notebook):
    for cell in notebook.cells:
        for result in cell.get("outputs", []):
            if result.output_type == "stream" and result.name == "stdout":
                for line in result.text.splitlines():
                    if line.startswith('{"cells":'):
                        return json.loads(line)
    raise ValueError("The notebook did not emit its QC summary.")


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    notebook = output / "pbmc3k.ipynb"
    if notebook.exists():
        raise ValueError("This run already has a notebook. Choose a fresh --output directory.")
    (output / "data").mkdir(exist_ok=True)
    document = jupytext.read(EXAMPLE / "analysis.py")
    if document.metadata.kernelspec.language != "python" or len(document.cells) != 1:
        raise ValueError("The demo must be a one-cell Python notebook.")
    pending = output / "pbmc3k.pending.ipynb"
    nbformat.write(document, pending)
    executed = execute_notebook(pending, output)
    provenance = dataset_provenance(output)
    summary = qc_summary(executed)
    if summary["cells"] != 2700:
        raise ValueError("The downloaded matrix does not contain the expected 2,700 cells.")
    shutil.copyfile(output / "pbmc3k-qc.png", output / "qc-before.png")
    write_json(output / "dataset.json", {**provenance, **summary})
    tokenizer(output)  # Cache the public vocabulary while this run has network access.
    pending.replace(notebook)
    return {"notebook": str(notebook), "figure": str(output / "qc-before.png"),
            "data": provenance, "qc": summary}


def workflow(output, arguments):
    output.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run([sys.executable, str(LAUNCHER), *arguments],
                               cwd=ROOT, capture_output=True, text=True)
    if completed.returncode:
        raise ValueError(completed.stderr.strip())
    response = json.loads(completed.stdout)
    with (output / "workflow-trace.jsonl").open("a") as stream:
        stream.write(json.dumps({"argv": ["python", str(LAUNCHER), *arguments],
                                 "response": response}) + "\n")
    if arguments[0] == "prepare":
        shutil.copyfile(response["script"], output / "script-before.py")
        write_json(output / "active-session.json", {"session": response["session"]})
    return response


def normalize_trace(events, output):
    """Remove machine paths/session IDs from the measured control text for portability."""
    text = json.dumps(events, indent=2, sort_keys=True)
    for event in events:
        session = event["response"].get("session")
        if session:
            text = text.replace(Path(session).name, "pbmc3k-<session-id>")
    for source, replacement in ((str(output), "<run>"), (str(ROOT), "<project>")):
        text = text.replace(source, replacement)
    return text


def report(output):
    session = Path(json.loads((output / "active-session.json").read_text())["session"])
    events = [json.loads(line) for line in (output / "workflow-trace.jsonl").read_text().splitlines()]
    expected = ["sessions", "prepare", "apply", "apply"]
    if [item["argv"][2] for item in events] != expected:
        raise ValueError("Expected one sessions/prepare/preview/apply trace for this run.")
    if "--dry-run" not in events[2]["argv"] or "--dry-run" in events[3]["argv"]:
        raise ValueError("The first apply must be a preview, and the second must apply.")
    applied = events[-1]["response"]
    if applied["changed"] != [1] or applied["outputs_cleared"] != [1]:
        raise ValueError("The demo must edit and clear exactly its single analysis cell.")

    # These files are read only by the local measurement helper, never printed into AI context.
    original_text = (session / "original.ipynb").read_text()
    original = nbformat.reads(original_text, as_version=4)
    notebook_path = output / "pbmc3k.ipynb"
    edited = nbformat.read(notebook_path, as_version=4)
    original_source = original.cells[0].source
    if original_source.count("bins=40") != 1 or edited.cells[0].source != original_source.replace("bins=40", "bins=60", 1):
        raise ValueError("Only the requested histogram bin count may change.")
    if edited.cells[0].outputs or edited.cells[0].execution_count is not None:
        raise ValueError("Apply must clear the old execution state before the rerun.")
    if edited.cells[0].id != original.cells[0].id or edited.metadata != original.metadata:
        raise ValueError("Apply must preserve the cell ID and notebook metadata.")

    encoding = tokenizer(output)
    prompt = (EXAMPLE / "request.txt").read_text().strip()
    script = (output / "script-before.py").read_text()
    skill = (ROOT / "skills/notebook-refactor/SKILL.md").read_text()
    control = normalize_trace(events, output)
    payloads = {"notebook_and_request": prompt + "\n\n" + original_text,
                "script_and_request": prompt + "\n\n" + script,
                "skill_including_overhead": prompt + "\n\n" + script + "\n\n" + skill + "\n\n" + control,
                "cell_source_and_request": prompt + "\n\n" + original_source}
    tokens = {name: len(encoding.encode_ordinary(text)) for name, text in payloads.items()}
    saved = tokens["notebook_and_request"] - tokens["skill_including_overhead"]
    inline_images = [item["data"]["image/png"] for item in original.cells[0].outputs
                     if "image/png" in item.get("data", {})]
    result = {"measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "dataset": json.loads((output / "dataset.json").read_text()),
              "edit_request": prompt, "encoding": "o200k_base", "tokens": tokens,
              "tokens_saved_including_overhead": saved,
              "reduction_percent_including_overhead": 100 * saved / tokens["notebook_and_request"],
              "notebook_bytes_before": len(original_text.encode()),
              "script_bytes_before": len(script.encode()),
              "code_cells": len(original.cells), "kernel": original.metadata.kernelspec.name,
              "inline_png_count_before": len(inline_images),
              "inline_png_bytes_before": sum(len(base64.b64decode(data)) for data in inline_images),
              "skill_instructions_tokens": len(encoding.encode_ordinary(skill)),
              "control_trace_tokens": len(encoding.encode_ordinary(control)),
              "workflow": {"changed": applied["changed"], "outputs_cleared": applied["outputs_cleared"],
                           "dependents_cleared": applied["dependents_cleared"],
                           "dependency_fallback": applied["dependency_fallback"],
                           "dependency_warnings": applied["dependency_warnings"]},
              "measurement": "Concatenated input text, not billed requests or total conversation tokens. Control paths are normalized; no model call is made by this helper.",
              "versions": {"python": sys.version.split()[0], **{name: version(name) for name in ("scanpy", "anndata", "numpy", "scipy", "matplotlib", "nbclient", "ipykernel", "tiktoken", "jupytext", "nbformat", "notebook-workflow")}}}
    rerun = execute_notebook(notebook_path, output)
    if qc_summary(rerun) != qc_summary(original):
        raise ValueError("QC values changed after the display-only edit.")
    shutil.copyfile(output / "pbmc3k-qc.png", output / "qc-after.png")
    result["qc_values_unchanged"] = True
    result["notebook_has_regenerated_outputs"] = any("image/png" in item.get("data", {}) for item in rerun.cells[0].outputs)
    if not result["notebook_has_regenerated_outputs"]:
        raise ValueError("The rerun did not store its figure in the notebook.")
    write_json(output / "report.json", result)
    return result


def replay(output):
    """Deterministic reproduction of the CLI edit; does not invoke an AI model."""
    created = generate(output)
    workflow(output, ["sessions", created["notebook"]])
    prepared = workflow(output, ["prepare", created["notebook"], "--editor", "off"])
    script = Path(prepared["script"])
    source = script.read_text()
    if source.count("bins=40") != 1:
        raise ValueError("Expected exactly one histogram bin setting.")
    script.write_text(source.replace("bins=40", "bins=60", 1))
    workflow(output, ["apply", prepared["session"], "--dry-run"])
    workflow(output, ["apply", prepared["session"]])
    return report(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "report", "replay"):
        commands.add_parser(name)
    launcher = commands.add_parser("workflow", help="record and run the maintained skill launcher")
    launcher.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        if args.command == "workflow":
            if not args.arguments:
                raise ValueError("Provide a workflow command and its arguments.")
            result = workflow(output, args.arguments)
        else:
            result = {"generate": generate, "report": report, "replay": replay}[args.command](output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"PBMC3k demo: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
