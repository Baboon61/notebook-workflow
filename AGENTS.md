# Notebook Workflow development

- Keep the tool and bundled skill independent of scientific projects and analysis libraries.
- Use an isolated local tooling environment; preserve users' Python/R analysis environments.
- Determine the Jupyter kernel before choosing a text representation: Python uses `.py` percent scripts and R uses `.R` percent scripts.
- Prefer Jupytext representations and preserve cell boundaries. For an assistance session, the converter exports the latest saved notebook to a temporary script rather than using a potentially stale permanent pair.
- AI assistance reads and edits that script. The local converter owns notebook JSON, backups, baselines, and merging; do not load those artifacts into AI context.
- Preserve existing `workflow_id` labels, scientific behavior, notebook metadata, and unaffected cell state. New cells have unlabeled boundaries.
- Move substantial reusable implementation into appropriate modules following the target project's conventions.
- Preserve the conservative default dependency policy and report dependency clearing and uncertainty.
- Validate previews, saved/unsaved conflict checks, exact no-op behavior, and recovery. Refuse overwriting newer edits and retain recovery artifacts.
- Do not directly edit `.ipynb` JSON unless specifically required. Use synthetic fixtures and isolated copies for converter tests.
- Do not execute analysis notebooks or expensive analyses automatically.
- Run relevant Python and Node tests after changes. Editor integration changes also need an isolated VS Code extension-host check.
- Keep runtime dependencies limited to the declared conversion tools. Do not change package or environment strategy unnecessarily.
- Use delegation only when explicitly authorized by the user or applicable instructions.
- Never run ANY Git command without explicit user approval for the exact command.
