"""Estimate a pragmatic Stage4 error-floor band from holdout departures."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _dehaan_sigma_mps(alt_m: float) -> float:
    if alt_m < 1000.0:
        return 1.4
    if alt_m < 3000.0:
        return 1.3
    if alt_m < 6000.0:
        return 1.2
    return 1.1


def _emaddc_sigma_mps(alt_m: float) -> float:
    if alt_m < 3000.0:
        return 2.2
    if alt_m < 6000.0:
        return 2.5
    return 2.8


def _altitude_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0-3km"
    if alt_m < 6000.0:
        return "3-6km"
    if alt_m < 9000.0:
        return "6-9km"
    if alt_m < 12000.0:
        return "9-12km"
    return "12km+"


def _rms(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return float("nan")
    return math.sqrt(sum(value * value for value in finite) / len(finite))


def _mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return float("nan")
    return sum(finite) / len(finite)


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    overall = report["overall"]
    lines = [
        "# Stage4 error-floor estimate",
        "",
        f"- Generated: `{report['generated_utc']}`",
        f"- Source CSV: `{report['point_csv']}`",
        f"- Holdout points: `{overall['point_count']}`",
        "",
        "## Overall",
        "",
        f"- Baseline vector RMSE: `{overall['baseline_vector_rmse_mps']:.6f}` m/s",
        f"- Baseline component RMSE: `{overall['baseline_component_rmse_mps']:.6f}` m/s",
        f"- EMADDC prior component sigma RMS: `{overall['emaddc_component_sigma_rms_mps']:.6f}` m/s",
        f"- de Haan prior component sigma RMS: `{overall['dehaan_component_sigma_rms_mps']:.6f}` m/s",
        f"- Observation-only vector lower bound: `{overall['observation_only_vector_floor_mps']:.6f}` m/s",
        f"- Local proxy vector floor: `{overall['proxy_vector_floor_mps']:.6f}` m/s",
        f"- Excess variance fraction vs EMADDC prior: `{overall['excess_variance_fraction_vs_emaddc']:.6f}`",
        f"- Distance from baseline to proxy floor: `{overall['baseline_minus_proxy_floor_mps']:.6f}` m/s",
        "",
        "## Caveat",
        "",
        "This is a pragmatic floor band, not a full triple-collocation result.",
        "It combines aircraft observation-error priors with holdout-neighbor representativeness proxies already present in the Stage4 departures CSV.",
        "Use it to bound realistic improvement space before heavier Stage4/Stage5 tuning.",
        "",
        "## Altitude bands",
        "",
        "| Bin | Points | Vector RMSE | Component RMSE | EMADDC sigma RMS | Proxy vector floor | Excess variance fraction |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["altitude_bins"]:
        lines.append(
            "| {bin} | {count} | {vrmse:.6f} | {crmse:.6f} | {em:.6f} | {floor:.6f} | {excess:.6f} |".format(
                bin=row["altitude_bin"],
                count=row["point_count"],
                vrmse=row["baseline_vector_rmse_mps"],
                crmse=row["baseline_component_rmse_mps"],
                em=row["emaddc_component_sigma_rms_mps"],
                floor=row["proxy_vector_floor_mps"],
                excess=row["excess_variance_fraction_vs_emaddc"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate a practical Stage4 error-floor band from point departures.")
    parser.add_argument("--point-csv", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    with args.point_csv.open("r", encoding="utf-8", newline="") as f:
        rows.extend(dict(row) for row in csv.DictReader(f))

    vector_sq: list[float] = []
    component_sq: list[float] = []
    emaddc_component_sigma: list[float] = []
    dehaan_component_sigma: list[float] = []
    neighbor_min_component_proxy: list[float] = []
    by_altitude: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        alt_m = _safe_float(row.get("alt_m"), 0.0)
        u_error = _safe_float(row.get("u_error"))
        v_error = _safe_float(row.get("v_error"))
        vector_error = _safe_float(row.get("vector_error"))
        if not math.isfinite(vector_error) and math.isfinite(u_error) and math.isfinite(v_error):
            vector_error = math.sqrt(u_error * u_error + v_error * v_error)
        if not math.isfinite(vector_error):
            continue
        if math.isfinite(u_error) and math.isfinite(v_error):
            comp = math.sqrt((u_error * u_error + v_error * v_error) / 2.0)
        else:
            comp = vector_error / math.sqrt(2.0)
        em_sigma = _emaddc_sigma_mps(alt_m)
        dh_sigma = _dehaan_sigma_mps(alt_m)
        neighbor_min = _safe_float(row.get("point_neighbor_min_vector_error"))
        neighbor_proxy_component = neighbor_min / math.sqrt(2.0) if math.isfinite(neighbor_min) and neighbor_min >= 0.0 else float("nan")

        vector_sq.append(vector_error)
        component_sq.append(comp)
        emaddc_component_sigma.append(em_sigma)
        dehaan_component_sigma.append(dh_sigma)
        neighbor_min_component_proxy.append(neighbor_proxy_component)

        alt_bin = _altitude_bin(alt_m)
        by_altitude[alt_bin]["vector_error"].append(vector_error)
        by_altitude[alt_bin]["component_error"].append(comp)
        by_altitude[alt_bin]["em_sigma"].append(em_sigma)
        by_altitude[alt_bin]["neighbor_proxy_component"].append(neighbor_proxy_component)

    baseline_vector_rmse = _rms(vector_sq)
    baseline_component_rmse = _rms(component_sq)
    emaddc_component_sigma_rms = _rms(emaddc_component_sigma)
    dehaan_component_sigma_rms = _rms(dehaan_component_sigma)
    neighbor_proxy_component_rms = _rms(neighbor_min_component_proxy)
    observation_only_vector_floor = math.sqrt(2.0) * emaddc_component_sigma_rms
    proxy_component_floor = math.sqrt(
        max(0.0, emaddc_component_sigma_rms * emaddc_component_sigma_rms + neighbor_proxy_component_rms * neighbor_proxy_component_rms)
    )
    proxy_vector_floor = min(baseline_vector_rmse, math.sqrt(2.0) * proxy_component_floor)
    excess_variance_fraction = max(
        0.0,
        min(1.0, 1.0 - (emaddc_component_sigma_rms * emaddc_component_sigma_rms) / max(baseline_component_rmse * baseline_component_rmse, 1e-12)),
    )

    altitude_rows: list[dict[str, Any]] = []
    for alt_bin in ["0-3km", "3-6km", "6-9km", "9-12km", "12km+"]:
        bucket = by_altitude.get(alt_bin)
        if not bucket:
            continue
        bin_component_rmse = _rms(bucket["component_error"])
        bin_em_sigma_rms = _rms(bucket["em_sigma"])
        bin_neighbor_proxy_rms = _rms(bucket["neighbor_proxy_component"])
        bin_proxy_component_floor = math.sqrt(
            max(0.0, bin_em_sigma_rms * bin_em_sigma_rms + bin_neighbor_proxy_rms * bin_neighbor_proxy_rms)
        )
        altitude_rows.append(
            {
                "altitude_bin": alt_bin,
                "point_count": len(bucket["vector_error"]),
                "baseline_vector_rmse_mps": _rms(bucket["vector_error"]),
                "baseline_component_rmse_mps": bin_component_rmse,
                "emaddc_component_sigma_rms_mps": bin_em_sigma_rms,
                "proxy_vector_floor_mps": min(_rms(bucket["vector_error"]), math.sqrt(2.0) * bin_proxy_component_floor),
                "excess_variance_fraction_vs_emaddc": max(
                    0.0,
                    min(1.0, 1.0 - (bin_em_sigma_rms * bin_em_sigma_rms) / max(bin_component_rmse * bin_component_rmse, 1e-12)),
                ),
            }
        )

    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "point_csv": str(args.point_csv),
        "overall": {
            "point_count": len(component_sq),
            "baseline_vector_rmse_mps": baseline_vector_rmse,
            "baseline_component_rmse_mps": baseline_component_rmse,
            "emaddc_component_sigma_rms_mps": emaddc_component_sigma_rms,
            "dehaan_component_sigma_rms_mps": dehaan_component_sigma_rms,
            "neighbor_min_component_proxy_rms_mps": neighbor_proxy_component_rms,
            "observation_only_vector_floor_mps": observation_only_vector_floor,
            "proxy_vector_floor_mps": proxy_vector_floor,
            "baseline_minus_proxy_floor_mps": max(0.0, baseline_vector_rmse - proxy_vector_floor),
            "excess_variance_fraction_vs_emaddc": excess_variance_fraction,
            "method_note": (
                "Observation priors come from EMADDC/de Haan altitude bins. The proxy floor adds the local "
                "point-neighbor minimum vector-error diagnostic as a representativeness term. This is a bounded "
                "engineering estimate, not a formal triple-collocation proof."
            ),
        },
        "altitude_bins": altitude_rows,
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(args.out_md, report)
    print(args.out_json)
    print(args.out_md)


if __name__ == "__main__":
    main()
