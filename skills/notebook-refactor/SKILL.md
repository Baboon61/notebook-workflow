---
name: notebook-refactor
description: Assist with saved Python or R Jupyter notebooks through output-free Jupytext scripts, then apply cell edits back while preserving unaffected outputs. Use for notebook code changes, debugging, or refactoring.
---

# Notebook Assistance

The user works in an interactive notebook. Run local conversion tooling before
and after AI assistance; read and edit only the exported `.py` or `.R` script.
The tool handles notebook JSON, outputs, metadata, backups, and cell matching.
This works with any Python/R project, including local notebook files connected
to a remote kernel. No analysis environment is needed for conversion.

## Start

1. Identify the saved `.ipynb` in scope. If given a paired `.py` or `.R`, resolve
   its sibling notebook. Ask only if the intended notebook cannot be determined.
2. The user pauses notebook editing and execution until application finishes.
   With the VS Code extension connected, preparation saves the current open
   notebook automatically. Without a connected editor, preparation uses the
   saved file; request a save only if its freshness is uncertain.
3. Run `python <this-skill>/scripts/workflow.py sessions <notebook.ipynb>`.
   If a prepared session exists, run `resume <session>` and use its existing
   edited script. Do not create another export or discard unfinished changes.
   Otherwise run `prepare <notebook.ipynb>`.
   New sessions live in the visible `notebook-workflow-sessions/` folder beside
   the notebook. Keep its backup and baseline files outside AI context.
   Do not request another pairing decision for a notebook editing task: this is
   a temporary assistance export, and leaves the original and any existing
   paired script untouched.
4. Use the returned `script`, `session`, and `language`. Python kernels export
   `.py` percent scripts; R kernels export `.R` percent scripts. Unknown kernels
   stop with a request to select a supported kernel and save.
   Inspect `editor.connected`: if true, VS Code saved its buffer. For workflows
   requiring the editor bridge, pass `--editor required` to prepare and apply.

The `<this-skill>` path is the directory of the SKILL.md you loaded; do not assume
a repository path. The launcher finds the separately installed local tooling
environment. See [workflow.md](references/workflow.md) for installation, editor
handling, recovery, and limitations.

## Edit

- Read and edit the returned script. Do not read `.ipynb`, `original.ipynb`, or
  `baseline.json` into AI context. For a plot/error-based request, use the plot or
  error supplied by the user; request the specific evidence if needed.
- Keep cell boundaries, Markdown narrative, and each existing `workflow_id`
  label. To add or duplicate a cell, add a percent boundary without a label.
  To remove a cell, remove its full block. To reorder, move its block and label.
- Leave YAML header settings and `# notebook-workflow-literal` comments intact.
  Jupytext may comment notebook magics and encode their language in boundaries;
  preserve those conventions. Percent scripts are transport, not necessarily
  ordinary executable scripts.
- Make changes needed for the assistance request. Extract reusable code into
  modules only when that task calls for it; follow the project's conventions.
  Do not impose package structure, data libraries, or an environment strategy.
- Preserve behavior unrelated to the request, including scientific parameters,
  seeds, mutable-object semantics, and global state. Flag intended behavior
  changes and hidden state that affects the result.
- Do not execute full notebooks or expensive analyses automatically. Use
  relevant lightweight validation. A Python/R conversion does not verify that
  its scientific code runs successfully in the remote kernel.
- Follow the project's Git permissions. This workflow never needs Git.

## Finish

1. Run `python <this-skill>/scripts/workflow.py apply <session> --dry-run` and
   inspect the compact change summary. Check that cells changed as intended,
   including `dependents_cleared`, `dependency_fallback`, and dependency warnings.
   The default policy clears identifiable direct/transitive dependencies and
   all later code cells when static analysis is uncertain. Do not silently
   disable that policy to preserve stale outputs.
2. Run `python <this-skill>/scripts/workflow.py apply <session>`. Apply even for a
   no-change task to close the session. No notebook is rewritten on a no-op.
3. If apply reports a conflict or damaged mapping, stop notebook mutation,
   retain the script, and report the specific error. Do not bypass the check or
   overwrite the notebook through Jupytext sync. See the recovery reference.
   Use `review <session>` to create a lightweight baseline script for a diff
   without opening backup JSON. Use `abort <session>` to close a prepared session
   only when it should be abandoned; it retains both script and backup and leaves
   the current notebook unchanged. A new preparation can then start.
4. Report edited cells separately from cells cleared because of dependencies
   or uncertainty. These cells lose outputs, execution counts, and execution
   timing; their source, IDs and other metadata are preserved. Unaffected cells
   keep their execution state. New code cells start without outputs.
5. Inspect the result's `editor` field. A connected editor refreshes and verifies
   applied code automatically. If `editor.error` is present, the file was already
   applied; report the refresh issue and reopen without saving a stale buffer.
   Retry with `refresh <session>` to refresh the saved result without reapplying.
   Without a connected editor, ask the user to check the loaded file. Rerun
   affected cells in their selected kernel. Changes to definitions/parameters
   can require rerunning downstream cells; their preserved outputs may be stale.

Start/finish automation is performed by the assistant following these steps.
The installed VS Code bridge saves before prepare and refreshes after apply;
there is no unconditional AI turn-end hook. A crash or interrupted task can
leave a prepared session; retain it for recovery. Resume can reconnect after a
VS Code reload to a unique clean editor. Connected sessions refuse operations
when their bridge is unavailable or the notebook buffer is dirty; do not bypass
with --editor off. Required editor mode also refuses a closed notebook. Restore
checks the editor and refreshes the restored file.

## Optional roles

Installed custom agents provide analyzer, refactorer, verifier, and architecture
roles. Use delegation only when the user or applicable instructions authorize
it. Give workers the exported script, detected language, session path, request,
and relevant project conventions. One owner applies the session after writers
finish. These agents inherit the parent's model and permissions.
