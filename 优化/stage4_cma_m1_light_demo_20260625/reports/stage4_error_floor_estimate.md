# Stage4 error-floor estimate

- Generated: `2026-06-25T09:45:46.755932Z`
- Source CSV: `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv`
- Holdout points: `530`

## Overall

- Baseline vector RMSE: `14.769036` m/s
- Baseline component RMSE: `10.443285` m/s
- EMADDC prior component sigma RMS: `2.734638` m/s
- de Haan prior component sigma RMS: `1.125041` m/s
- Observation-only vector lower bound: `3.867362` m/s
- Local proxy vector floor: `11.112602` m/s
- Excess variance fraction vs EMADDC prior: `0.931431`
- Distance from baseline to proxy floor: `3.656433` m/s

## Caveat

This is a pragmatic floor band, not a full triple-collocation result.
It combines aircraft observation-error priors with holdout-neighbor representativeness proxies already present in the Stage4 departures CSV.
Use it to bound realistic improvement space before heavier Stage4/Stage5 tuning.

## Altitude bands

| Bin | Points | Vector RMSE | Component RMSE | EMADDC sigma RMS | Proxy vector floor | Excess variance fraction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0-3km | 39 | 5.687122 | 4.021403 | 2.200000 | 4.656706 | 0.700711 |
| 3-6km | 47 | 8.440119 | 5.968065 | 2.500000 | 7.654876 | 0.824526 |
| 6-9km | 85 | 7.638472 | 5.401216 | 2.800000 | 7.136283 | 0.731260 |
| 9-12km | 137 | 11.451702 | 8.097576 | 2.800000 | 9.786013 | 0.880434 |
| 12km+ | 222 | 19.917698 | 14.083939 | 2.800000 | 14.168927 | 0.960475 |
