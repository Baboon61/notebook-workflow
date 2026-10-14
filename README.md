# Notebook Workflow

Use Codex to debug, edit, and refactor Python and R notebooks, then continue
running cells in VS Code with your existing kernel.

Notebook Workflow is a Codex skill and local tool that gives the assistant your
notebook's code and Markdown without its stored cell outputs. It brings edits
back into the original notebook and preserves unaffected results, so AI
assistance fits into your interactive analysis workflow.

## Why use it?

A saved notebook contains more than code. Charts, images, and other cell outputs
can make the file large. When an assistant reads the full notebook file, those
stored results can consume much of its context. A code edit also needs to account
for old results that may no longer match the calculation.

Notebook Workflow helps you:

- **Give the assistant useful context.** It works from the code and explanatory
  notes in a lightweight script, with stored cell outputs kept outside its input.
- **Keep unaffected results.** Independent plots and outputs remain available;
  results affected by code changes are cleared for rerunning.
- **Keep your existing environment.** Conversion runs locally in its own tooling
  environment. Your Python or R kernel and analysis dependencies stay in place.
- **Use one installation across projects.** The skill follows each project's
  conventions without depending on a particular scientific library or dataset.

The reduction in input size depends on the notebook and how your assistant
normally reads it. Notebooks with large saved outputs benefit most; Markdown,
including any inline image data, remains in the script.

## When to use it

Use it for requests such as:

- Fixing notebook code after an error.
- Moving repeated analysis code into reusable functions or project modules.
- Updating a calculation or parameter while preserving the surrounding analysis.

For example:

```text
Use $notebook-refactor to update notebooks/analysis.ipynb:
Move the repeated preprocessing into a reusable function and preserve its behavior.
```

## How it works

1. **Prepare.** The saved notebook is exported to a temporary script containing
   its code and notes. The VS Code integration saves the open notebook first.
2. **Edit.** Codex works on that script and, when your request calls for it,
   relevant project modules.
3. **Preview and apply.** The tool previews the cell changes and applies them
   back to the notebook. Changed code and dependent cells lose their saved
   outputs; unaffected cells keep their state. Uncertain dependencies trigger
   broader clearing, reported in the preview.
4. **Continue your analysis.** Inspect the refreshed notebook and rerun affected
   cells using your chosen kernel.

Your notebook remains the source of truth. Pause its editing and execution during
assistance; the tool refuses conflicting edits and retains recovery backups.
It does not execute your analysis automatically.

## Get started

You need Python 3.10+ for the local tool, Codex, and VS Code for the integrated
notebook workflow. Download or clone this repository into a stable local folder,
then run from its root:

```bash
python3 install.py
python3 install.py --vscode-only
```

The second command requires the VS Code `code` command on PATH. Reload VS Code
and restart Codex if the skill has not appeared. Open a saved Python or R notebook
and ask for help using `$notebook-refactor`, as in the example above.

Locally stored notebooks can use local or remote kernels. The editor integration
has been validated on macOS; see the [installation guide](docs/installation.md)
for platform scope, manual save/reopen without VS Code, and migration from an
older installation.

## Documentation and examples

- [Installation](docs/installation.md): setup, custom paths, CLI-only use, and migration.
- [Usage and recovery](skills/notebook-refactor/references/workflow.md): previews,
  dependency handling, unfinished sessions, and restoring a notebook.
- [Python example](examples/python.py) and [R example](examples/r.R): small notebooks
  to try, with [conversion instructions](docs/development.md#try-the-examples).
- [Development](docs/development.md): tests, packaging, and contributions.

Released under the [MIT license](LICENSE).
