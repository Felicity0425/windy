# Stage4 Error Resolution Workflow

This folder contains the dedicated code path for Stage4 error-priority work.

Purpose:

- Keep error-resolution experiments separate from the generic `core` scripts.
- Run the priority order defined in
  `workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage4_error_resolution_plan_20260602.md`.
- Promote only the candidates that pass guardrails after a direct pairwise comparison.

Current entry point:

- `stage4_priority_runner.py`
- `stage4_refinement_runner.py`
- `stage4_narrow_grid_refinement_runner.py`

Current workflow:

1. Re-run `timepower15` and the current `adaptive_v3` seed with a clean 25-worker setup.
2. Apply the error-priority phases one by one.
3. After each phase, compare the new candidate against the currently promoted active candidate.
4. Promote the new candidate only if its phase-specific guardrail passes.
5. Keep writing pairwise comparison and error-source decomposition outputs for every phase.

Focused refinement workflow:

1. Start from the current promoted active candidate.
2. Run a small 25-worker candidate set around that winner.
3. Compare each refinement candidate directly against the current active baseline.
4. Emit a `run_best_full_25w.sh` script for the strongest surviving candidate.

Narrow-grid refinement workflow:

1. Start from the currently best refined candidate.
2. Sweep a very small local grid, e.g. `context_time_conf_power` and
   `conflict_speed_threshold_mps`, with 25-worker metrics-only runs.
3. Keep the grid narrow and deterministic so that differences stay interpretable.
4. Use this workflow before attempting any larger structural change.

Notes:

- `representation_error` and `tail_qc` are treated as diagnostic/reporting phases first.
- `vertical_structure`, `sparse_support`, `role_conflict`, `temporal_weighting`, and `localization`
  can promote a new active candidate.
- All metrics remain strict aircraft holdout only.
