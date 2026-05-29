from __future__ import annotations

"""Stage-local configuration wrapper.

This module loads the project-level `pipeline_config.py` under a distinct
module name so stage scripts can import `pipeline_config` from the `stage/`
directory without creating circular imports.
"""

import importlib.util
from pathlib import Path

_STAGE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _STAGE_DIR.parent
_ROOT_CONFIG = _ROOT_DIR / "pipeline_config.py"
_ROOT_CONFIG_FALLBACK = _ROOT_DIR / "pipeline_utils.py"

# [改动说明] 服务器/本地环境里根目录可能没有 pipeline_config.py，
# 因此这里增加 fallback，回退到根目录 pipeline_utils.py。ROOT_CONFIG_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load root pipeline config: {_ROOT_CONFIG_PATH}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_module, _name)

_ROOT_CONFIG_PATH = _ROOT_CONFIG if _ROOT_CONFIG.exists() else _ROOT_CONFIG_FALLBACK

_spec = importlib.util.spec_from_file_location("pengxu_root_pipeline_config", _