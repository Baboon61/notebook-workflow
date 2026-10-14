# PBMC3k execution results

**Verification: Passed.** Measured at 2026-10-14T13:05:46.311814+00:00 (UTC).

The demo uses 2,700 cells and 32,738 genes from
`scanpy.datasets.pbmc3k()`. The edit changes the RNA-count histogram from
40 to 60 bins. The notebook runs before and after applying the edit.

## Token comparison

| Input text | Tokens |
| --- | ---: |
| Full saved notebook + request, without the skill | 61,715 |
| Exported script + request | 710 |
| Skill workflow, including instructions and command/response summaries | 2,895 |
| Cell source + request, for an assistant that already extracts source | 491 |

**58,820 fewer input-text tokens
(95.31% reduction)** compared
with reading the full saved notebook, including the skill's overhead.

Encoding: `o200k_base`. Skill instructions: 1,420
tokens; command/response text: 765 tokens.
Original notebook: 94,376 bytes; exported script:
2,347 bytes. The notebook contains
1 real inline PNG (68,397 bytes).

These are concatenated input-text payload counts, not billed model usage or
total conversation tokens. The replay command makes no model call. Command paths and session
directory names are normalized; rendering, download messages, paths, and generated
cell labels can change counts. An assistant that already reads only source starts
with the smaller source-only baseline above; this percentage saving does not apply
to that baseline.

## Edit and execution checks

Requested edit:

> Change the RNA-count histogram from 40 to 60 bins. Preserve all QC calculations and the scatter plot.

| Check | Result |
| --- | --- |
| Edited cells | 1 |
| Cells whose old outputs were cleared | 1 |
| Additional dependent cells cleared | None |
| Cells flagged by conservative dependency analysis | 1 |
| QC summary values unchanged after rerunning | Yes |
| Inline figure regenerated | Yes |

Before writing this report, the runner checks that only `bins=40` changes to
`bins=60`, cell IDs and notebook metadata are preserved, and the old outputs
and execution count are cleared before rerunning.

Dependency warnings:

- Cell 1: Control flow may conditionally redefine notebook variables.

A dependency warning records uncertainty in static analysis, rather than an
execution failure. This one-cell demo has no later cells to clear.

## QC summary before and after

| Metric | Value |
| --- | ---: |
| Cells | 2,700 |
| Genes | 32,738 |
| Median RNA counts | 2,197 UMIs |
| Median detected genes | 817 |
| Median mitochondrial RNA | 2.029639% |

## Figures

Before: 40 histogram bins.

![PBMC3k QC before the edit, with a 40-bin histogram.](figures/qc-before.png)

After: 60 histogram bins, with unchanged QC values and scatter plot.

![PBMC3k QC after the edit, with a 60-bin histogram.](figures/qc-after.png)

## Dataset and environment

Dataset download: [https://exampledata.scverse.org/scanpy/pbmc3k_raw.h5ad](https://exampledata.scverse.org/scanpy/pbmc3k_raw.h5ad).
SHA-256: `89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1`. Download size: 5,855,727 bytes.

| Package | Version |
| --- | --- |
| anndata | 0.13.4 |
| ipykernel | 7.4.0 |
| jupytext | 1.19.6 |
| matplotlib | 3.11.2 |
| nbclient | 0.11.0 |
| nbformat | 5.11.1 |
| notebook-workflow | 0.4.0 |
| numpy | 2.5.4 |
| python | 3.14.6 |
| scanpy | 1.12.4 |
| scipy | 1.18.1 |
| tiktoken | 0.14.0 |

The [JSON report](report.json) contains the same measurements in machine-readable
form. This Markdown file links to figures and does not embed dataset contents.
