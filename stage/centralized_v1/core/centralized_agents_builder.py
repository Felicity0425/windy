"""Centralized v1 Ground Center agent builder.

This builder consumes centralized Stage2 ``flight_raw_records`` and emits the
Stage3 agent fields used by the Ground Center payload. It deliberately keeps
the centralized rules:

- every valid flight agent can downlink to Ground Center;
- no Air-to-Air graph is active in the mainline;
- aircraft motion is diagnostic support, not atmospheric wind truth;
- spatial distance to the reference center is diagnostic only.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from stage.centralized_v1.configs.centralized_v1_contract import (
    C3_AGENT_ALT,
    C3_AGENT_DELTA_TIME_MIN,
    C3_AGENT_DISTANCE_KM,
    C3_AGENT_IDS,
    C3_AGENT_JOINT_CONF,
    C3_AGENT_LAT,
    C3_AGENT_LON,
    C3_AGENT_SPACE_CONF,
    C3_AGENT_TIME_CONF,
    C3_AGENT_TO_CENTER_ALLOWED,
)


def _to_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, pl.DataFrame):
        return value.to_dicts()
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return []
        value = value.tolist()
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
            elif hasattr(item, "items"):
                out.append(dict(item.items()))
        return out
    return []


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in (
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _median(values: list[float], default: float = 0.0) -> float:
    if not values:
        return float(default)
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.mean(np.asarray(values, dtype=np.float64)))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * radius_km * math.asin(min(1.0, math.sqrt(a)))


def _empty_agents(reference: dict[str, Any] | None = None) -> dict[str, Any]:
    ref = reference or {}
    return {
        C3_AGENT_IDS: [],
        C3_AGENT_LAT: [],
        C3_AGENT_LON: [],
        C3_AGENT_ALT: [],
        C3_AGENT_DELTA_TIME_MIN: [],
        C3_AGENT_DISTANCE_KM: [],
        C3_AGENT_TIME_CONF: [],
        C3_AGENT_SPACE_CONF: [],
        C3_AGENT_JOINT_CONF: [],
        C3_AGENT_TO_CENTER_ALLOWED: [],
        "agent_record_count": [],
        "agent_voxel_count": [],
        "agent_motion_u_mean": [],
        "agent_motion_v_mean": [],
        "agent_motion_speed_mean": [],
        "center_downlink_src": [],
        "center_downlink_dst": [],
        "center_downlink_allowed": [],
        "center_downlink_weight": [],
        "agent_builder": "centralized_agents_builder",
        "agent_builder_role": "ground_center_all_agents_downlink_diagnostic_motion_only",
        "agent_reference_center_source": ref.get("source", "unavailable"),
        "agent_reference_center_lat": ref.get("lat"),
        "agent_reference_center_lon": ref.get("lon"),
        "agent_reference_center_alt_m": ref.get("alt_m"),
        "agent_virtual_flight_count": 0,
        "agent_virtual_record_count": 0,
    }


def empty_ground_center_agents(reference_center: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return an empty agent package for the no-agent mainline mode."""

    return _empty_agents(reference_center)


def _reference_center(records: list[dict[str, Any]], reference_center: dict[str, Any] | None) -> dict[str, Any]:
    if reference_center:
        lat = _safe_float(reference_center.get("lat"))
        lon = _safe_float(reference_center.get("lon"))
        alt = _safe_float(reference_center.get("alt_m"))
        if lat is not None and lon is not None and alt is not None:
            return {
                "lat": lat,
                "lon": lon,
                "alt_m": alt,
                "source": reference_center.get("source", "stage2_reference_center"),
            }

    lats = [_safe_float(row.get("lat_clean")) for row in records]
    lons = [_safe_float(row.get("lon_clean")) for row in records]
    alts = [_safe_float(row.get("alt_meters")) for row in records]
    lats = [v for v in lats if v is not None]
    lons = [v for v in lons if v is not None]
    alts = [v for v in alts if v is not None]
    return {
        "lat": _median(lats, 33.2),
        "lon": _median(lons, 104.0),
        "alt_m": _median(alts, 0.0),
        "source": "agent_median_fallback",
    }


def build_ground_center_agents(
    flight_records: Any,
    target_time: datetime | None,
    alpha: float,
    *,
    reference_center: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build centralized Stage3 Ground Center agents from Stage2 flight rows."""

    rows = _to_records(flight_records)
    if not rows:
        return _empty_agents(reference_center)

    grouped: dict[str, list[dict[str, Any]]] = {}
    virtual_ids: set[str] = set()
    virtual_record_count = 0
    for row in rows:
        fid = str(row.get("flight_id", "")).strip()
        if not fid:
            continue
        lat = _safe_float(row.get("lat_clean"))
        lon = _safe_float(row.get("lon_clean"))
        alt = _safe_float(row.get("alt_meters"))
        if lat is None or lon is None or alt is None:
            continue
        grouped.setdefault(fid, []).append(row)
        if bool(row.get("flight_id_is_virtual", False)):
            virtual_ids.add(fid)
            virtual_record_count += 1

    if not grouped:
        return _empty_agents(reference_center)

    ref = _reference_center(rows, reference_center)
    out = _empty_agents(ref)

    for fid in sorted(grouped):
        items = grouped[fid]
        lats: list[float] = []
        lons: list[float] = []
        alts: list[float] = []
        u_vals: list[float] = []
        v_vals: list[float] = []
        deltas: list[float] = []
        voxels: set[tuple[int, int, int]] = set()
        for row in items:
            lat = _safe_float(row.get("lat_clean"))
            lon = _safe_float(row.get("lon_clean"))
            alt = _safe_float(row.get("alt_meters"))
            if lat is not None:
                lats.append(lat)
            if lon is not None:
                lons.append(lon)
            if alt is not None:
                alts.append(alt)
            u = _safe_float(row.get("u_motion"))
            v = _safe_float(row.get("v_motion"))
            if u is not None:
                u_vals.append(u)
            if v is not None:
                v_vals.append(v)
            z = row.get("z")
            y = row.get("y")
            x = row.get("x")
            if z is not None and y is not None and x is not None:
                try:
                    voxels.add((int(z), int(y), int(x)))
                except (TypeError, ValueError):
                    pass
            row_time = _parse_datetime(row.get("time_utc"))
            if target_time is not None and row_time is not None:
                deltas.append(abs((row_time - target_time).total_seconds()) / 60.0)

        lat = _median(lats)
        lon = _median(lons)
        alt = _median(alts)
        delta_min = min(deltas) if deltas else 0.0
        time_conf = math.exp(-float(alpha) * float(delta_min))
        space_conf = 1.0
        joint_conf = time_conf
        dist_km = _haversine_km(lat, lon, float(ref["lat"]), float(ref["lon"]))
        u_mean = _mean(u_vals)
        v_mean = _mean(v_vals)
        if u_mean is None or v_mean is None:
            motion_speed = None
        else:
            motion_speed = float(math.sqrt(u_mean * u_mean + v_mean * v_mean))

        out[C3_AGENT_IDS].append(fid)
        out[C3_AGENT_LAT].append(lat)
        out[C3_AGENT_LON].append(lon)
        out[C3_AGENT_ALT].append(alt)
        out[C3_AGENT_DELTA_TIME_MIN].append(float(delta_min))
        out[C3_AGENT_DISTANCE_KM].append(float(dist_km))
        out[C3_AGENT_TIME_CONF].append(float(time_conf))
        out[C3_AGENT_SPACE_CONF].append(space_conf)
        out[C3_AGENT_JOINT_CONF].append(float(joint_conf))
        out[C3_AGENT_TO_CENTER_ALLOWED].append(1.0)
        out["agent_record_count"].append(int(len(items)))
        out["agent_voxel_count"].append(int(len(voxels)))
        out["agent_motion_u_mean"].append(u_mean)
        out["agent_motion_v_mean"].append(v_mean)
        out["agent_motion_speed_mean"].append(motion_speed)
        out["center_downlink_src"].append(fid)
        out["center_downlink_dst"].append("ground_center")
        out["center_downlink_allowed"].append(1.0)
        out["center_downlink_weight"].append(float(joint_conf))

    out["agent_virtual_flight_count"] = int(sum(1 for fid in out[C3_AGENT_IDS] if fid in virtual_ids))
    out["agent_virtual_record_count"] = int(virtual_record_count)
    return out


__all__ = ["build_ground_center_agents", "empty_ground_center_agents"]
