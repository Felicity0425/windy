"""Compatibility wrapper for wind reconstruction.

This module exists so newer stage code can import the shared reconstruction
baseline from a stage-local path, while the actual implementation lives in
`reconstruct_utils.py`.
"""

from reconstruct_utils import _reconstruct_wind_field

__all__ = ["_reconstruct_wind_field"]
