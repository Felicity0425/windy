"""Shared helper facade for the pipeline.

This module keeps stage scripts away from direct `hello.py` imports while
reusing the existing mature helper implementations. As we progressively
extract helpers into pipeline-local modules, this file becomes the stable
compatibility layer for Stage 2/3/4.
"""

from stage.hello import (
    _compute_flight_intent,
    _eval_agent_geo,
    _ff_demand_score,
    _ff_edge_score,
    _haversine_km,
    _linear_conf,
    _read_gray_image_robust,
    _save_sparse_lossless_npz,
    _space_likelihood,
    _time_likelihood,
    _zyx_to_linear_idx,
)

__all__ = [
    "_compute_flight_intent",
    "_eval_agent_geo",
    "_ff_demand_score",
    "_ff_edge_score",
    "_haversine_km",
    "_linear_conf",
    "_read_gray_image_robust",
    "_save_sparse_lossless_npz",
    "_space_likelihood",
    "_time_likelihood",
    "_zyx_to_linear_idx",
]
