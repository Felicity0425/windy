from __future__ import annotations

"""Stage-local configuration wrapper.

This module lets scripts inside `stage/` import `pipeline_config` while still
using the project-level configuration from the repository root.
"""

import importlib.util
from pathlib import Path

_STAGE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _STAGE_DIR.parent
_ROOT_CONFIG = _ROOT_DIR / "pipeline_config.py"
_ROOT_CONFIG_FALLBACK = _ROOT_DIR / "pipeline_utils.py"
_ROOT_CONFIG_PATH = _ROOT_CONFIG if _ROOT_CONFIG.exists() else _ROOT_CONFIG_FALLBACK

_spec = importlib.util.spec_from_file_location(
    "pengxu_root_pipeline_config",
    _ROOT_CONFIG_PATH,
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load root pipeline config: {_ROOT_CONFIG_PATH}")

_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_module, _name)
