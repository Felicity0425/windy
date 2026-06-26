# Own Data P0-LEAK Audit

## Scope

Audited the project's own data sources:

- `20260224/amdar.xlsx` -> `amdar_parquet`
- `20260224/turb.xlsx` -> `turb_parquet`
- `20260224/location.xlsx` -> `location_location_parquet`
- Stage2/Stage3 derivatives from these sources

## Evidence

- `clean_wind.parquet`: 431,189 rows
  - `amdar`: 431,008
  - `turb`: 181
  - time range: `2026-01-22 16:00:39` to `2026-02-23 15:59:41`
  - altitude range: `2010` to `767384` m
- `clean_loc.parquet`: 19,162,638 rows
  - time range: `2026-01-22 18:00:25` to `2026-02-23 17:59:31`
  - altitude range: `7.62` to `30000.0` m
- Stage2: 7,395 frames
  - `stage2_role = observation_organization_not_reconstruction`
  - `all_in_observations = 1`
- Stage3: 7,395 frames
  - `agent_builder_enabled = false`
  - `agent_mode = none`

## P0-LEAK Check

- `strict_holdout_no_leakage`: yes, for Stage4 train/holdout splitting
- `background_independent_of_holdout`: no, because these sources are the project's own observations
- `reanalysis / forecast` test: not applicable

## Conclusion

- These self data sources can replace CMA as `training observations`.
- They cannot replace CMA as an `independent background` in the P0-LEAK sense.
- If used naively as background, they collapse the background/analysis distinction and do not unlock OI / Desroziers.
- To replace CMA as background, you need either:
  - an external independent forecast/reanalysis prior, or
  - a self-built prior trained only on disjoint historical data and evaluated on strict holdout.

## Practical Verdict

- `Can replace CMA for observations?` yes
- `Can replace CMA for background immediately?` no
- `Can replace CMA for M1 display-fill?` only if converted into a separate, holdout-independent prior branch
