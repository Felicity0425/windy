"""Shared field-name contract for Stage-2/3/4 pipeline outputs.

Keep all serialized key names in one place so the stages stay aligned.
"""

from __future__ import annotations

# Stage-2 npz keys
STAGE2_FILENAME = "filename"
STAGE2_TIME_STR = "time_str"
STAGE2_TIMESTAMP_UTC = "timestamp_utc"
STAGE2_RADAR_SHAPE = "radar_shape"
STAGE2_GRID_SHAPE = "grid_shape"
STAGE2_RADAR_IMG = "radar_img"
STAGE2_WIND_RECORDS = "wind_records"
STAGE2_LOC_RECORDS = "loc_records"
STAGE2_MOTION_RECORDS = "motion_records"
STAGE2_FLIGHT_MOTION_RECORDS = "flight_motion_records"
STAGE2_FLIGHT_RAW_RECORDS = "flight_raw_records"
STAGE2_AMDAR_RECORDS = "amdar_records"
STAGE2_TURB_RECORDS = "turb_records"

# Stage-3 JSON keys / Stage-4 agent pack keys
STAGE3_VOX_PATH = "vox_path"
STAGE3_VALID_FLIGHT_AGENTS = "valid_flight_agents"
STAGE3_CANDIDATE_FLIGHT_COUNT = "candidate_flight_count"
STAGE3_TIER1_CANDIDATE_COUNT = "tier1_candidate_count"
STAGE3_TIER2_CANDIDATE_COUNT = "tier2_candidate_count"
STAGE3_VALID_WIND_CAPABLE_FLIGHTS = "valid_wind_capable_flights"
STAGE3_FLIGHT_COMM_ALLOWED_AGENTS = "flight_comm_allowed_agents"
STAGE3_FLIGHT_FF_ALLOWED_EDGES = "flight_ff_allowed_edges"
STAGE3_FLIGHT_FF_MOTION_EDGES = "flight_ff_motion_edges"
STAGE3_FLIGHT_FF_WIND_EDGES = "flight_ff_wind_edges"

# Flight pack / npz keys
FLIGHT_COMM_ALLOWED = "flight_comm_allowed"
FLIGHT_COMM_WEIGHT = "flight_comm_weight"
FLIGHT_FF_COMM_ALLOWED = "ff_comm_allowed"
FLIGHT_FF_COMM_WEIGHT = "ff_comm_weight"
FLIGHT_FF_MOTION_ALLOWED = "ff_motion_allowed"
FLIGHT_FF_MOTION_WEIGHT = "ff_motion_weight"
FLIGHT_FF_WIND_ALLOWED = "ff_wind_allowed"
FLIGHT_FF_WIND_WEIGHT = "ff_wind_weight"
FLIGHT_MASK = "flight_mask"
FLIGHT_TOPK = "flight_topk"

# Reconstruction / packed output keys
RECON_U_3D = "recon_u_3d"
RECON_V_3D = "recon_v_3d"
RECON_CONF_3D = "recon_confidence_3d"
RECON_MASK_3D = "recon_mask_3d"
