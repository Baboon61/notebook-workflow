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
    from ipykernel.kernelspec import get_kernel_dict
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    from nbclient import NotebookClient

    kernels = output / "kernel-specs"
    spec = kernels / "python3"
    spec.mkdir(parents=True, exist_ok=True)
    kernel_spec = get_kernel_dict()  # Uses this process's sys.executable.
    kernel_spec["display_name"] = "PBMC3k demo"
    write_json(spec / "kernel.json", kernel_spec)
    manager = KernelManager(kernel_name="python3", connection_file=str(output / "kernel-connection.json"),
                            transport_encryption="required",
                            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]))
    environment = dict(os.environ)
    environment.update({"MPLCONFIGDIR": str(output / "matplotlib-cache"),
                        "MPLBACKEND": "module://matplotlib_inline.backend_inline",
                        "IPYTHONDIR": str(output / "ipython"),
                        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                        "NUMBA_NUM_THREADS": "1"})
    notebook = nbformat.read(path, as_version=4)
    # A supplied manager is caller-owned; explicitly clean it up after this run.
    NotebookClient(notebook, km=manager, timeout=120, record_timing=False,
                   resources={"metadata": {"path": str(output)}}).execute(env=environment, cleanup_kc=True)
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


def write_markdown_report(output, result, *, figures_directory="."):
    """Write a readable summary from the same measurements as report.json."""
    tokens = result["tokens"]
    data = result["dataset"]
    changes = result["workflow"]
    figures = Path(figures_directory)

    def cells(values):
        return ", ".join(str(value) for value in values) or "None"

    warnings = "\n".join(f"- Cell {item['cell']}: {item['reason']}"
                         for item in changes["dependency_warnings"]) or "None."
    versions = "\n".join(f"| {name} | {value} |" for name, value in result["versions"].items())
    status = "Passed" if (result["qc_values_unchanged"] and
                          result["notebook_has_regenerated_outputs"]) else "Failed"
    text = f"""# PBMC3k execution results

**Verification: {status}.** Measured at {result['measured_at_utc']} (UTC).

The demo uses {data['cells']:,} cells and {data['genes']:,} genes from
`scanpy.datasets.pbmc3k()`. The edit changes the RNA-count histogram from
40 to 60 bins. The notebook runs before and after applying the edit.

## Token comparison

| Input text | Tokens |
| --- | ---: |
| Full saved notebook + request, without the skill | {tokens['notebook_and_request']:,} |
| Exported script + request | {tokens['script_and_request']:,} |
| Skill workflow, including instructions and command/response summaries | {tokens['skill_including_overhead']:,} |
| Cell source + request, for an assistant that already extracts source | {tokens['cell_source_and_request']:,} |

**{result['tokens_saved_including_overhead']:,} fewer input-text tokens
({result['reduction_percent_including_overhead']:.2f}% reduction)** compared
with reading the full saved notebook, including the skill's overhead.

Encoding: `{result['encoding']}`. Skill instructions: {result['skill_instructions_tokens']:,}
tokens; command/response text: {result['control_trace_tokens']:,} tokens.
Original notebook: {result['notebook_bytes_before']:,} bytes; exported script:
{result['script_bytes_before']:,} bytes. The notebook contains
{result['inline_png_count_before']} real inline PNG ({result['inline_png_bytes_before']:,} bytes).

These are concatenated input-text payload counts, not billed model usage or
total conversation tokens. The replay command makes no model call. Command paths and session
directory names are normalized; rendering, download messages, paths, and generated
cell labels can change counts. An assistant that already reads only source starts
with the smaller source-only baseline above; this percentage saving does not apply
to that baseline.

## Edit and execution checks

Requested edit:

> {result['edit_request']}

| Check | Result |
| --- | --- |
| Edited cells | {cells(changes['changed'])} |
| Cells whose old outputs were cleared | {cells(changes['outputs_cleared'])} |
| Additional dependent cells cleared | {cells(changes['dependents_cleared'])} |
| Cells flagged by conservative dependency analysis | {cells(changes['dependency_fallback'])} |
| QC summary values unchanged after rerunning | {'Yes' if result['qc_values_unchanged'] else 'No'} |
| Inline figure regenerated | {'Yes' if result['notebook_has_regenerated_outputs'] else 'No'} |

Before writing this report, the runner checks that only `bins=40` changes to
`bins=60`, cell IDs and notebook metadata are preserved, and the old outputs
and execution count are cleared before rerunning.

Dependency warnings:

{warnings}

A dependency warning records uncertainty in static analysis, rather than an
execution failure. This one-cell demo has no later cells to clear.

## QC summary before and after

| Metric | Value |
| --- | ---: |
| Cells | {data['cells']:,} |
| Genes | {data['genes']:,} |
| Median RNA counts | {data['median_umis']:,.0f} UMIs |
| Median detected genes | {data['median_detected_genes']:,.0f} |
| Median mitochondrial RNA | {data['median_mito_percent']:.6f}% |

## Figures

Before: 40 histogram bins.

![PBMC3k QC before the edit, with a 40-bin histogram.]({(figures / 'qc-before.png').as_posix()})

After: 60 histogram bins, with unchanged QC values and scatter plot.

![PBMC3k QC after the edit, with a 60-bin histogram.]({(figures / 'qc-after.png').as_posix()})

## Dataset and environment

Dataset download: [{data['url']}]({data['url']}).
SHA-256: `{data['file_sha256']}`. Download size: {data['file_bytes']:,} bytes.

| Package | Version |
| --- | --- |
{versions}

The [JSON report](report.json) contains the same measurements in machine-readable
form. This Markdown file links to figures and does not embed dataset contents.
"""
    path = output / "report.md"
    path.write_text(text, encoding="utf-8")
    return path


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
    result["markdown_report"] = str(output / "report.md")
    write_json(output / "report.json", result)
    write_markdown_report(output, result)
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
