"""Shared helpers for Stage5 background loading.

These helpers keep Stage5 background handling lightweight and robust across:

- historical GFS/GDAS ROI NPZ files
- locally downloaded ERA5 ROI NetCDF files

The intent is to treat all of them as *background priors*, not dense local
truth fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

try:
    from netCDF4 import Dataset
except Exception:  # pragma: no cover - optional dependency
    Dataset = None


_PREFIXES = ("era5_roi", "gfs_roi", "gdas_roi", "merra2_roi", "background")
_EXTS = (".npz", ".nc", ".nc4")


def _pressure_to_alt_km(pressure_hpa: np.ndarray) -> np.ndarray:
    pressure = np.maximum(np.asarray(pressure_hpa, dtype=np.float32), 1.0)
    return (44330.0 * (1.0 - (pressure / 1013.25) ** 0.1903) / 1000.0).astype(np.float32, copy=False)


def resolve_background_path(path: Path | None, time_str: str) -> Path | None:
    if path is None:
        return None
    if path.is_file():
        return path if path.suffix.lower() in _EXTS else None

    candidate_dirs: list[Path] = []
    if path.exists():
        candidate_dirs.append(path)
    name = path.name
    if name.endswith("_npz"):
        alt = path.with_name(name[:-4])
        if alt.exists():
            candidate_dirs.append(alt)
    else:
        alt = path.with_name(f"{name}_npz")
        if alt.exists():
            candidate_dirs.append(alt)

    for base in candidate_dirs:
        for prefix in _PREFIXES:
            for ext in _EXTS:
                candidate = base / f"{prefix}_{time_str}{ext}"
                if candidate.exists():
                    return candidate

    if not time_str:
        for base in candidate_dirs:
            files = []
            for prefix in _PREFIXES:
                for ext in _EXTS:
                    files.extend(sorted(base.glob(f"{prefix}_*{ext}")))
            if files:
                return files[-1]
    return None


def _load_background_npz(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as npz:
        files = set(npz.files)
        required = {"lat", "lon", "alt_km", "u", "v"}
        missing = sorted(required - files)
        if missing:
            raise KeyError(f"{path} missing keys: {', '.join(missing)}")
        out: dict[str, Any] = {
            "path": str(path),
            "time_str": str(npz["time_str"]) if "time_str" in files else path.stem.split("_")[-1],
            "lat": np.asarray(npz["lat"], dtype=np.float32),
            "lon": np.asarray(npz["lon"], dtype=np.float32),
            "alt_km": np.asarray(npz["alt_km"], dtype=np.float32),
            "u": np.asarray(npz["u"], dtype=np.float32),
            "v": np.asarray(npz["v"], dtype=np.float32),
        }
        if "pressure_hpa" in files:
            out["pressure_hpa"] = np.asarray(npz["pressure_hpa"], dtype=np.float32)
        for key in ("w", "vertical_velocity", "temperature", "geopotential"):
            if key in files:
                out[key] = np.asarray(npz[key], dtype=np.float32)
    return out


def _coord(ds: Any, *names: str) -> np.ndarray:
    for name in names:
        if name in ds.variables:
            return np.asarray(ds.variables[name][:], dtype=np.float32)
    raise KeyError(f"Missing coordinate among: {', '.join(names)}")


def _var(ds: Any, *names: str) -> np.ndarray | None:
    for name in names:
        if name in ds.variables:
            arr = np.asarray(ds.variables[name][:], dtype=np.float32)
            while arr.ndim > 3:
                arr = arr[0]
            return arr
    return None


def _load_background_nc(path: Path) -> dict[str, Any]:
    if Dataset is None:
        raise RuntimeError("netCDF4 is required to read ERA5 NetCDF background files.")
    with Dataset(path) as ds:
        lat = _coord(ds, "latitude", "lat")
        lon = _coord(ds, "longitude", "lon")
        pressure = _coord(ds, "pressure_hpa", "pressure_level", "level", "lev", "isobaricInhPa")
        u = _var(ds, "u", "u_component_of_wind", "U")
        v = _var(ds, "v", "v_component_of_wind", "V")
        if u is None or v is None:
            raise KeyError(f"{path} does not contain u/v wind variables.")
        out: dict[str, Any] = {
            "path": str(path),
            "time_str": path.stem.split("_")[-1],
            "lat": lat.astype(np.float32, copy=False),
            "lon": lon.astype(np.float32, copy=False),
            "pressure_hpa": pressure.astype(np.float32, copy=False),
            "alt_km": _pressure_to_alt_km(pressure),
            "u": u.astype(np.float32, copy=False),
            "v": v.astype(np.float32, copy=False),
        }
        w = _var(ds, "w", "vertical_velocity", "OMEGA")
        if w is not None:
            out["w"] = w.astype(np.float32, copy=False)
            out["vertical_velocity"] = w.astype(np.float32, copy=False)
        z = _var(ds, "z", "geopotential", "H")
        if z is not None:
            out["geopotential"] = z.astype(np.float32, copy=False)
        t = _var(ds, "t", "temperature", "T")
        if t is not None:
            out["temperature"] = t.astype(np.float32, copy=False)
    return out


def load_background(path: Path | None, time_str: str) -> dict[str, Any] | None:
    candidate = resolve_background_path(path, time_str)
    if candidate is None or not candidate.exists():
        return None
    suffix = candidate.suffix.lower()
    if suffix == ".npz":
        out = _load_background_npz(candidate)
    elif suffix == ".nc":
        out = _load_background_nc(candidate)
    else:
        raise ValueError(f"Unsupported background format: {candidate}")
    if out["u"].ndim != 3 or out["v"].shape != out["u"].shape:
        raise ValueError(f"Expected background u/v shape (z,y,x), got {out['u'].shape}/{out['v'].shape}")
    if np.asarray(out["alt_km"]).size != np.asarray(out["u"]).shape[0]:
        raise ValueError(f"Background altitude axis length mismatch for {candidate}")
    return out


def load_background_candidates(paths: list[Path] | tuple[Path, ...] | None, time_str: str) -> list[dict[str, Any]]:
    if not paths:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        background = load_background(path, time_str)
        if background is not None:
            out.append(background)
    return out
