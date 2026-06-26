# Stage4 altitude cutoff report

- Generated: `2026-06-26T08:53:57.725914Z`
- Source CSV: `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv`
- Keep rule: `alt_m < 12000.0`

## Headline

- Total holdout points: `530`
- Kept points (`< 12000 m`): `308`
- Removed points (`>= 12000 m`): `222`
- Removed point fraction: `41.887%`
- Removed SSE fraction: `76.182%`

## Overall comparison

- All-point vector RMSE: `14.769036` m/s
- <= cutoff vector RMSE: `9.455171` m/s
- RMSE delta (kept - all): `-5.313865` m/s
- All-point vector MAE: `6.854454` m/s
- <= cutoff vector MAE: `5.653215` m/s
- MAE delta (kept - all): `-1.201239` m/s

## Frame-level comparison

- All-point frame mean RMSE: `8.224309` m/s
- <= cutoff frame mean RMSE: `6.188699` m/s
- All-point frame P95 RMSE: `27.986111` m/s
- <= cutoff frame P95 RMSE: `20.953949` m/s
- All-point frame P99 RMSE: `58.783770` m/s
- <= cutoff frame P99 RMSE: `39.044922` m/s
- Frames emptied by cutoff: `24`

## Light wind

- All-point `5-15 m/s` RMSE: `5.195877` m/s
- <= cutoff `5-15 m/s` RMSE: `5.458937` m/s
- All-point `5-15 m/s` MAE: `4.185283` m/s
- <= cutoff `5-15 m/s` MAE: `4.421286` m/s

## Kept altitude bins

| Bin | Points | Vector RMSE | Vector MAE | P95 | Tail>=30 count |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0-3km | 39 | 5.687122 | 3.631781 | 8.680026 | 0 |
| 3-6km | 47 | 8.440119 | 6.237626 | 14.837248 | 0 |
| 6-9km | 85 | 7.638472 | 5.404177 | 13.852334 | 1 |
| 9-12km | 137 | 11.451702 | 6.182682 | 23.716185 | 5 |

## Note

This report redefines the evaluation scope by excluding high-altitude holdout points.
It is useful for business-facing <=12 km diagnostics, but it is not directly comparable to the original all-altitude promotion gate unless that gate is also redefined.
