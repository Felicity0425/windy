# GitHub Backup Plan - 2026-05-29

This workspace uses GitHub for source code, scripts, configuration, and
handover documentation. It intentionally does not push large raw/generated data
through normal Git, because GitHub rejects files above 100 MB and large binary
history quickly becomes fragile.

## Tracked In Git

- `stage/`: legacy Stage1-Stage5 scripts, centralized_v1 scripts, configs,
  utilities, and handover Markdown/PDF notes.
- `workflow/`: project documentation, handovers, summaries, and literature
  notes used to reconstruct the project context.
- Root Python/config/Markdown files.
- Selected small quality reports from `20260224/`:
  - `location_location_quality_corrected_rates.csv`
  - `location_location_quality_report_fixed.json`
  - `location_location_quality_report.json`

## Excluded From Normal Git

- Local environments: `.conda/`, `.venv/`, `venv/`, `env/`.
- Generated outputs: `centralized_v1_output/`, `_organized_outputs/`,
  `stage5_visualizations/`.
- Large/raw data: `cma/`, most of `20260224/`, `windpaper/`, Excel, Parquet,
  NPZ/NPY, NetCDF, GRIB, HDF5, and archive bundles.
- Runtime logs under `stage/logs/`, `stage/logs_v2/`, and organized log views.

## Current Large Data Inventory

Approximate local sizes observed on 2026-05-29:

```text
.conda/          8.4G   local environment; should be recreated, not backed up
20260224/        2.9G   raw source data; includes location.xlsx at about 1.2G
cma/             1.7G   CMA/reanalysis source data
windpaper/        87M   paper/reference material
stage/            35M   source + docs, suitable for GitHub
workflow/         16M   docs/handover, suitable for GitHub
```

## Recommended Big-Data Backup

Use one of these instead of normal Git:

1. Object/cloud storage or NAS rsync for `20260224/`, `cma/`, and important
   output snapshots.
2. DVC with a remote storage backend if versioned data lineage is needed.
3. Git LFS only for selected medium binary artifacts, after confirming GitHub
   LFS quota and bandwidth.

## Local Git Command Note

This server has a read-only placeholder `.git/` directory at the workspace
root, so this checkout is managed with a separate Git metadata directory:

```bash
git --git-dir=/data/LFT-W02_data/pengxu/.git_meta_pengxu \
  --work-tree=/data/LFT-W02_data/pengxu status
```

For convenience in this shell:

```bash
alias gitp='git --git-dir=/data/LFT-W02_data/pengxu/.git_meta_pengxu --work-tree=/data/LFT-W02_data/pengxu'
```

