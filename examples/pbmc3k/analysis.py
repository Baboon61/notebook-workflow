# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %%
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import scanpy as sc

# Scanpy downloads the public 10x PBMC3k counts into this local cache.
sc.settings.datasetdir = Path("data")
adata = sc.datasets.pbmc3k()
adata.var["mt"] = adata.var_names.str.startswith("MT-")
sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)
total_umis = adata.obs["total_counts"].to_numpy()
detected_genes = adata.obs["n_genes_by_counts"].to_numpy()
mito_percent = adata.obs["pct_counts_mt"].to_numpy()

# Keep every supplied cell; this example computes QC without filtering or clustering.
print(json.dumps({"cells": adata.n_obs, "genes": adata.n_vars,
                  "median_umis": float(np.median(total_umis)),
                  "median_detected_genes": float(np.median(detected_genes)),
                  "median_mito_percent": float(np.median(mito_percent))}, sort_keys=True))

fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=120, layout="constrained")
axes[0].hist(total_umis, bins=40, color="#0072B2", edgecolor="white")
axes[0].set(xlabel="Total RNA counts (UMIs)", ylabel="Number of cells", title="RNA counts per cell")
points = axes[1].scatter(total_umis, detected_genes, c=mito_percent,
                         s=8, alpha=0.7, cmap="viridis")
axes[1].set(xlabel="Total RNA counts (UMIs)", ylabel="Detected genes", title="Per-cell quality control")
for axis in axes:
    axis.locator_params(axis="x", nbins=5)
fig.colorbar(points, ax=axes[1], label="Mitochondrial RNA (%)")
fig.suptitle(f"10x PBMC3k: {adata.n_obs:,} cells", fontsize=14)
fig.savefig("pbmc3k-qc.png", dpi=120, facecolor="white")
plt.show()
