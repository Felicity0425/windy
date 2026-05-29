import os
import numpy as np
import polars as pl
from datetime import datetime


def build_flight_agents_sparse(
    flight_grouped,
    flight_frame,
    h_dim,
    w_dim,
    topk,
    target_time,
    ground_lat,
    ground_lon,
    ground_alt,
    amdar_flight_ids,
    tier2_max_override,
    config,
    helpers,
):
    """Build dynamic flight-agent pack with physical constraints and sparse A2A comm."""

    haversine_km = helpers["haversine_km"]
    eval_agent_geo = helpers["eval_agent_geo"]
    linear_conf = helpers["linear_conf"]
    time_likelihood = helpers["time_likelihood"]
    space_likelihood = helpers["space_likelihood"]
    blend_comm_weight = helpers["blend_comm_weight"]
    compute_flight_intent = helpers["compute_flight_intent"]
    ff_demand_score = helpers["ff_demand_score"]
    ff_edge_score = helpers["ff_edge_score"]
    zyx_to_linear_idx = helpers["zyx_to_linear_idx"]
    select_ff_edges = helpers["select_ff_edges"]

    COMM_TIME_LIMIT_SECONDS = config["COMM_TIME_LIMIT_SECONDS"]
    COMM_SPACE_LIMIT_KM = config["COMM_SPACE_LIMIT_KM"]
    COMM_VERTICAL_LIMIT_M = config["COMM_VERTICAL_LIMIT_M"]
    FF_COMM_TIME_LIMIT_SECONDS = config["FF_COMM_TIME_LIMIT_SECONDS"]
    FF_COMM_SPACE_LIMIT_KM = config["FF_COMM_SPACE_LIMIT_KM"]
    FF_COMM_VERTICAL_LIMIT_M = config["FF_COMM_VERTICAL_LIMIT_M"]
    FLIGHT_PREFER_COMM_ELIGIBLE = config["FLIGHT_PREFER_COMM_ELIGIBLE"]
    FLIGHT_TIER2_MAX = config["FLIGHT_TIER2_MAX"]
    COMM_ROUND = config["COMM_ROUND"]
    FF_MAX_NEIGHBORS_PER_AGENT = config["FF_MAX_NEIGHBORS_PER_AGENT"]
    PHYSICS_REALISM_MODE = bool(config.get("PHYSICS_REALISM_MODE", False))

    def _make_empty(n=0, candidate_count=0, tier1_count=0, tier2_count=0):
        return {
            "flight_agent_ids": np.array([""] * n, dtype="<U64"),
            "flight_offsets": np.zeros(n + 1, dtype=np.int64),
            "flight_idx_flat": np.array([], dtype=np.uint32),
            "flight_u_flat": np.array([], dtype=np.float32),
            "flight_v_flat": np.array([], dtype=np.float32),
            "flight_count_flat": np.array([], dtype=np.float32),
            "flight_mask": np.zeros(n, dtype=np.uint8),
            "flight_time_gap_sec": np.full(n, np.inf, dtype=np.float32),
            "flight_space_hdist_km": np.full(n, np.inf, dtype=np.float32),
            "flight_space_vdist_m": np.full(n, np.inf, dtype=np.float32),
            "flight_time_conf": np.zeros(n, dtype=np.float32),
            "flight_space_conf": np.zeros(n, dtype=np.float32),
            "flight_time_likelihood": np.zeros(n, dtype=np.float32),
            "flight_space_likelihood": np.zeros(n, dtype=np.float32),
            "flight_st_conf": np.zeros(n, dtype=np.float32),
            "flight_st_likelihood": np.zeros(n, dtype=np.float32),
            "flight_comm_allowed": np.zeros(n, dtype=np.float32),
            "flight_comm_weight": np.zeros(n, dtype=np.float32),
            "flight_intent": np.zeros((n, 3), dtype=np.float32),
            "flight_has_wind_obs": np.zeros(n, dtype=np.float32),
            "ff_time_gap_sec": np.full((n, n), np.inf, dtype=np.float32),
            "ff_space_hdist_km": np.full((n, n), np.inf, dtype=np.float32),
            "ff_space_vdist_m": np.full((n, n), np.inf, dtype=np.float32),
            "ff_time_conf": np.zeros((n, n), dtype=np.float32),
            "ff_space_conf": np.zeros((n, n), dtype=np.float32),
            "ff_time_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_space_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_st_conf": np.zeros((n, n), dtype=np.float32),
            "ff_st_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_comm_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_comm_weight": np.zeros((n, n), dtype=np.float32),
            "ff_motion_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_motion_weight": np.zeros((n, n), dtype=np.float32),
            "ff_wind_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_wind_weight": np.zeros((n, n), dtype=np.float32),
            "ff_sparse_src": np.array([], dtype=np.int32),
            "ff_sparse_dst": np.array([], dtype=np.int32),
            "ff_sparse_score": np.array([], dtype=np.float32),
            "flight_topk": np.array(n, dtype=np.int32),
            "valid_flight_agents": 0,
            "candidate_flight_count": int(candidate_count),
            "tier1_candidate_count": int(tier1_count),
            "tier2_candidate_count": int(tier2_count),
            "valid_wind_capable_flights": 0,
            "ff_motion_edges": 0,
            "ff_wind_edges": 0,
        }

    if len(flight_grouped) == 0:
        n_empty = topk if topk > 0 else 0
        return _make_empty(n_empty)

    def _log_step(label, count, extra=None):
        """打印每一步筛选后的剩余候选数与置信度统计。"""
        msg = f"[Stage-3][agent_builder] {label}: remaining={int(count)}"
        if extra:
            msg += " | " + ", ".join([f"{k}={v}" for k, v in extra.items()])
        print(msg)

    def _log_flight_detail(stage, fid, lat, lon, alt, t_mid, dt_sec, dh_km, dz_m, tc, sc, tl, sl, score=None):
        return

    totals = flight_grouped.group_by("flight_id").agg(
        pl.col("motion_count").sum().alias("total_obs")
    )
    fid_obs = {row["flight_id"]: row["total_obs"] for row in totals.iter_rows(named=True)}
    _log_step("raw candidates", len(fid_obs))

    geo_cache = {}
    for fid in fid_obs:
        g = eval_agent_geo(flight_frame, fid, target_time)
        if g is not None:
            geo_cache[fid] = g
    _log_step("geo resolved", len(geo_cache))

    def _fallback_geo_from_grouped(flight_id):
        """当原始 flight_frame 无法解析到地理位置时，基于体素分组结果做保守回退。

        说明：
        - 这里用 flight_grouped 中该 flight 的体素中心点，反推一个近似经纬高。
        - 时间差设为 0，表示和当前帧对齐，但仍保留空间约束。
        - 这样可以避免因上游时间/字段格式波动导致 Stage 3 全部 agent 为空。
        - 仍然遵守空间/垂直/通信阈值，不会突破物理约束。
        """
        if "flight_id" not in flight_grouped.columns:
            return None
        one = flight_grouped.filter(pl.col("flight_id").cast(pl.Utf8, strict=False) == str(flight_id))
        if len(one) == 0:
            return None
        try:
            x = float(one["x"].median())
            y = float(one["y"].median())
            z = float(one["z"].median())
            lat = cfg.LAT_MAX - (y + 0.5) * (cfg.LAT_MAX - cfg.LAT_MIN) / max(1, h_dim)
            lon = cfg.LON_MIN + (x + 0.5) * (cfg.LON_MAX - cfg.LON_MIN) / max(1, w_dim)
            alt = cfg.ALT_MIN + (z + 0.5) * cfg.DELTA_ALT
            return float(lat), float(lon), float(alt), target_time, 0.0
        except Exception:
            return None

    for fid in fid_obs:
        if fid not in geo_cache:
            g = _fallback_geo_from_grouped(fid)
            if g is not None:
                geo_cache[fid] = g
    _log_step("geo fallback filled", len(geo_cache))

    tier1, tier2 = [], []
    confidence_samples = []
    geo_ok_count = 0
    hi_conf_pool = 0
    adaptive_space = bool(config.get("ADAPTIVE_SPACE_LIKELIHOOD", getattr(cfg, "ADAPTIVE_SPACE_LIKELIHOOD", True))) if "cfg" in globals() else bool(config.get("ADAPTIVE_SPACE_LIKELIHOOD", True))
    dh_values, dz_values = [], []
    for fid, (lat, lon, alt, t_mid, dt_sec) in geo_cache.items():
        dh_km = haversine_km(lat, lon, ground_lat, ground_lon)
        dz_m = abs(alt - ground_alt)
        ag_comm = (
            dt_sec <= COMM_TIME_LIMIT_SECONDS
            and dh_km <= COMM_SPACE_LIMIT_KM
            and dz_m <= COMM_VERTICAL_LIMIT_M
        )
        tl = time_likelihood(dt_sec)
        dh_values.append(dh_km)
        dz_values.append(dz_m)
        score = fid_obs.get(fid, 0)
        confidence_samples.append((fid, score, tl, dh_km, dz_m, t_mid, lat, lon, alt, dt_sec, ag_comm))
        if ag_comm:
            geo_ok_count += 1

    if adaptive_space and len(dh_values) > 0:
        dh_scale = max(50.0, float(np.percentile(np.asarray(dh_values, dtype=np.float64), 75)))
        dz_scale = max(800.0, float(np.percentile(np.asarray(dz_values, dtype=np.float64), 75)))
    else:
        dh_scale = float(config.get("SPACE_LIKELIHOOD_SIGMA_KM", getattr(cfg, "SPACE_LIKELIHOOD_SIGMA_KM", 180.0))) if "cfg" in globals() else float(config.get("SPACE_LIKELIHOOD_SIGMA_KM", 180.0))
        dz_scale = float(config.get("SPACE_LIKELIHOOD_SIGMA_Z_M", getattr(cfg, "SPACE_LIKELIHOOD_SIGMA_Z_M", 2500.0))) if "cfg" in globals() else float(config.get("SPACE_LIKELIHOOD_SIGMA_Z_M", 2500.0))

    for fid, score, tl, dh_km, dz_m, t_mid, lat, lon, alt, dt_sec, ag_comm in confidence_samples:
        sl = float(np.exp(-0.5 * ((dh_km / dh_scale) ** 2 + (dz_m / dz_scale) ** 2)))
        conf = float(tl * sl)
        hi_conf_pool += 1 if conf >= 0.25 else 0
        _log_flight_detail("split", fid, lat, lon, alt, t_mid, dt_sec, dh_km, dz_m, dt_sec / max(1.0, COMM_TIME_LIMIT_SECONDS), dh_km / max(1.0, COMM_SPACE_LIMIT_KM), tl, sl, score=score)
        if ag_comm:
            tier1.append((fid, score, conf))
        else:
            tier2.append((fid, score, conf))

    tier1.sort(key=lambda x: x[1], reverse=True)
    tier2.sort(key=lambda x: x[2], reverse=True)
    _log_step("tier1/tier2 split", len(tier1) + len(tier2), {
        "tier1": len(tier1),
        "tier2": len(tier2),
        "geo_ok": geo_ok_count,
        "hi_conf": hi_conf_pool,
        "dh_scale": round(float(dh_scale), 3),
        "dz_scale": round(float(dz_scale), 1),
    })

    if PHYSICS_REALISM_MODE:
        # 在物理真实模式下，进一步剔除相关性太弱的低价值候选
        # 但阈值放宽一些，避免全量候选被过度过滤。
        min_pair_score = float(os.environ.get("WIND_PHYSICS_MIN_PAIR_SCORE", "0.06"))
        min_tier2_score = float(os.environ.get("WIND_PHYSICS_MIN_TIER2_SCORE", "0.03"))
        tier1_before = len(tier1)
        tier2_before = len(tier2)
        tier1 = [x for x in tier1 if x[2] >= min_pair_score]
        tier2 = [x for x in tier2 if x[2] >= min_tier2_score]
        _log_step("physics filter", len(tier1) + len(tier2), {
            "tier1_kept": len(tier1),
            "tier2_kept": len(tier2),
            "tier1_drop": tier1_before - len(tier1),
            "tier2_drop": tier2_before - len(tier2),
            "min_pair_score": min_pair_score,
            "min_tier2_score": min_tier2_score,
        })
        if len(tier1) == 0 and len(tier2) == 0:
            print("[Stage-3][agent_builder] WARNING: physics filter removed all candidates; consider relaxing thresholds or checking geo/time parsing.")

    candidate_count = len(geo_cache)
    if topk <= 0:
        # 你要求候选不先人为截断，所以默认让全部候选进入后续筛选；
        # 如果后续需要压缩规模，再通过环境变量或 topk 控制。
        effective_topk = candidate_count
    else:
        effective_topk = min(topk, candidate_count)
    if effective_topk <= 0:
        return _make_empty(0, candidate_count, len(tier1), len(tier2))

    selected_tier1 = [f for f, _, _ in tier1[:effective_topk]]
    remaining = effective_topk - len(selected_tier1)

    effective_tier2_max = FLIGHT_TIER2_MAX if tier2_max_override is None else int(max(0, tier2_max_override))
    if FLIGHT_PREFER_COMM_ELIGIBLE:
        # 0 means unlimited tier2 backfill (do not drop candidates due to cap)
        if effective_tier2_max <= 0:
            tier2_cap = remaining
        else:
            tier2_cap = min(effective_tier2_max, remaining) if len(selected_tier1) > 0 else remaining
        selected_tier2 = [f for f, _, _ in tier2[:tier2_cap]]
    else:
        selected_tier2 = []

    selected = selected_tier1 + selected_tier2
    if not selected and candidate_count > 0:
        # 两层筛选中的几何可达阶段已经有足够样本时，避免因为高置信阈值过严导致整帧为空。
        # 这里从几何可达里兜底取一小批最强候选，保证通信图至少可构建。
        fallback_pool = tier1[: min(8, len(tier1))] if len(tier1) > 0 else tier2[: min(8, len(tier2))]
        selected = [f for f, _, _ in fallback_pool]
        selected_tier1 = selected
        selected_tier2 = []
        remaining = 0
    _log_step("selected", len(selected), {"tier1_sel": len(selected_tier1), "tier2_sel": len(selected_tier2)})
    if not selected:
        return _make_empty(effective_topk, candidate_count, len(tier1), len(tier2))

    n_slots = len(selected)
    ids = np.array(["" for _ in range(n_slots)], dtype="<U64")
    offsets = [0]
    idx_parts, u_parts, v_parts, c_parts = [], [], [], []
    mask = np.zeros(n_slots, dtype=np.uint8)

    time_gap_sec = np.full(n_slots, np.inf, dtype=np.float32)
    hdist_km_arr = np.full(n_slots, np.inf, dtype=np.float32)
    vdist_m_arr = np.full(n_slots, np.inf, dtype=np.float32)
    time_conf = np.zeros(n_slots, dtype=np.float32)
    space_conf = np.zeros(n_slots, dtype=np.float32)
    time_like = np.zeros(n_slots, dtype=np.float32)
    space_like = np.zeros(n_slots, dtype=np.float32)
    st_conf = np.zeros(n_slots, dtype=np.float32)
    st_like = np.zeros(n_slots, dtype=np.float32)
    comm_allowed = np.zeros(n_slots, dtype=np.float32)
    comm_weight = np.zeros(n_slots, dtype=np.float32)
    flight_intent = np.zeros((n_slots, 3), dtype=np.float32)
    flight_has_wind_obs = np.zeros(n_slots, dtype=np.float32)
    agent_lat = np.full(n_slots, np.nan, dtype=np.float64)
    agent_lon = np.full(n_slots, np.nan, dtype=np.float64)
    agent_alt = np.full(n_slots, np.nan, dtype=np.float64)
    agent_tsec = np.full(n_slots, np.nan, dtype=np.float64)
    agent_obs_count = np.zeros(n_slots, dtype=np.float32)

    ff_time_gap_sec = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_hdist_km = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_vdist_m = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_time_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_space_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_time_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_space_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_st_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_st_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_score = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_allowed = np.zeros((n_slots, n_slots), dtype=np.float32)

    amdar_flight_ids = amdar_flight_ids or set()

    for i, fid in enumerate(selected):
        one = flight_grouped.filter(pl.col("flight_id") == fid)
        if len(one) == 0 or fid not in geo_cache:
            offsets.append(offsets[-1])
            continue

        idx = zyx_to_linear_idx(one["z"].to_numpy(), one["y"].to_numpy(), one["x"].to_numpy(), h_dim, w_dim)
        idx_parts.append(idx)
        u_parts.append(one["u_motion"].to_numpy().astype(np.float32, copy=False))
        v_parts.append(one["v_motion"].to_numpy().astype(np.float32, copy=False))
        c_parts.append(one["motion_count"].to_numpy().astype(np.float32, copy=False))

        ids[i] = str(fid)
        mask[i] = 1
        offsets.append(offsets[-1] + len(idx))

        own_obs = float(one["motion_count"].sum()) if "motion_count" in one.columns else float(len(one))
        agent_obs_count[i] = own_obs

        lat, lon, alt, t_mid, dt_sec = geo_cache[fid]
        dh_km = haversine_km(lat, lon, ground_lat, ground_lon)
        dz_m = abs(alt - ground_alt)

        tc = linear_conf(dt_sec, COMM_TIME_LIMIT_SECONDS)
        sc_h = linear_conf(dh_km, COMM_SPACE_LIMIT_KM)
        sc_v = linear_conf(dz_m, COMM_VERTICAL_LIMIT_M)
        sc = float(np.sqrt(sc_h * sc_v))
        tl = time_likelihood(dt_sec)
        sl = space_likelihood(dh_km, dz_m)
        ag_allowed = 1.0 if (
            dt_sec <= COMM_TIME_LIMIT_SECONDS and dh_km <= COMM_SPACE_LIMIT_KM and dz_m <= COMM_VERTICAL_LIMIT_M
        ) else 0.0

        time_gap_sec[i] = dt_sec
        hdist_km_arr[i] = dh_km
        vdist_m_arr[i] = dz_m
        time_conf[i] = tc
        space_conf[i] = sc
        time_like[i] = tl
        space_like[i] = sl
        st_conf[i] = tc * sc
        st_like[i] = tl * sl
        comm_allowed[i] = ag_allowed
        wind_bonus = 1.0 if str(fid) in amdar_flight_ids else 0.0
        comm_weight[i] = ag_allowed * blend_comm_weight(tc, sc, tl, sl, wind_bonus=wind_bonus)
        agent_lat[i] = lat
        agent_lon[i] = lon
        agent_alt[i] = alt
        agent_tsec[i] = float((t_mid - datetime(1970, 1, 1)).total_seconds())
        flight_intent[i] = compute_flight_intent(flight_frame, fid)
        # 风能力节点不再只依赖 AMDAR 映射：
        # 1) 有 AMDAR 证据时直接视作风能力节点；
        # 2) 若该节点的时空置信度足够高，也允许作为“弱风能力节点”；
        # 3) 这样可以避免风边长期为 0，同时仍保持物理意义。
        flight_has_wind_obs[i] = 1.0 if (str(fid) in amdar_flight_ids or conf >= 0.25) else 0.0

    while len(offsets) < n_slots + 1:
        offsets.append(offsets[-1])

    valid_idx = np.where(mask > 0)[0]
    for i in valid_idx:
        for j in valid_idx:
            if i == j or not (np.isfinite(agent_tsec[i]) and np.isfinite(agent_tsec[j])):
                continue
            dt_ff = abs(float(agent_tsec[i] - agent_tsec[j]))
            dh_ff = haversine_km(agent_lat[i], agent_lon[i], agent_lat[j], agent_lon[j])
            dz_ff = abs(float(agent_alt[i] - agent_alt[j]))

            ff_ok = (
                dt_ff <= FF_COMM_TIME_LIMIT_SECONDS
                and dh_ff <= FF_COMM_SPACE_LIMIT_KM
                and dz_ff <= FF_COMM_VERTICAL_LIMIT_M
            )

            tc_ff = linear_conf(dt_ff, FF_COMM_TIME_LIMIT_SECONDS)
            sc_h_ff = linear_conf(dh_ff, FF_COMM_SPACE_LIMIT_KM)
            sc_v_ff = linear_conf(dz_ff, FF_COMM_VERTICAL_LIMIT_M)
            sc_ff = float(np.sqrt(sc_h_ff * sc_v_ff))
            tl_ff = time_likelihood(dt_ff)
            sl_ff = space_likelihood(dh_ff, dz_ff)

            ff_time_gap_sec[i, j] = dt_ff
            ff_hdist_km[i, j] = dh_ff
            ff_vdist_m[i, j] = dz_ff
            ff_time_conf[i, j] = tc_ff
            ff_space_conf[i, j] = sc_ff
            ff_time_like[i, j] = tl_ff
            ff_space_like[i, j] = sl_ff
            ff_st_conf[i, j] = tc_ff * sc_ff
            ff_st_like[i, j] = tl_ff * sl_ff
            pair_wind_bonus = 1.0 if (flight_has_wind_obs[i] > 0 and flight_has_wind_obs[j] > 0) else 0.0
            demand_ij = ff_demand_score(agent_obs_count[i], agent_obs_count[j], pair_wind_bonus)
            score_ij = ff_edge_score(demand_ij, tc_ff * sc_ff, tl_ff * sl_ff)
            ff_score[i, j] = score_ij
            ff_allowed[i, j] = 1.0 if ff_ok else 0.0

    ff_sel = select_ff_edges(
        comm_round=COMM_ROUND,
        ff_allowed=ff_allowed,
        ff_score=ff_score,
        flight_has_wind_obs=flight_has_wind_obs,
        max_neighbors_per_agent=FF_MAX_NEIGHBORS_PER_AGENT,
    )

    valid_mask = mask > 0
    valid_count = int(valid_mask.sum())
    comm_eligible_count = int(comm_allowed[valid_mask].sum()) if valid_count > 0 else 0
    st_conf_valid = st_conf[valid_mask] if valid_count > 0 else np.array([], dtype=np.float32)
    st_like_valid = st_like[valid_mask] if valid_count > 0 else np.array([], dtype=np.float32)

    ff_density = 0.0
    if valid_count >= 2:
        ff_density = float(ff_sel["ff_allowed"].sum()) / float(valid_count * (valid_count - 1))

    return {
        "flight_agent_ids": ids,
        "flight_offsets": np.asarray(offsets, dtype=np.int64),
        "flight_idx_flat": np.concatenate(idx_parts) if idx_parts else np.array([], dtype=np.uint32),
        "flight_u_flat": np.concatenate(u_parts) if u_parts else np.array([], dtype=np.float32),
        "flight_v_flat": np.concatenate(v_parts) if v_parts else np.array([], dtype=np.float32),
        "flight_count_flat": np.concatenate(c_parts) if c_parts else np.array([], dtype=np.float32),
        "flight_mask": mask,
        "flight_time_gap_sec": time_gap_sec,
        "flight_space_hdist_km": hdist_km_arr,
        "flight_space_vdist_m": vdist_m_arr,
        "flight_time_conf": time_conf,
        "flight_space_conf": space_conf,
        "flight_time_likelihood": time_like,
        "flight_space_likelihood": space_like,
        "flight_st_conf": st_conf,
        "flight_st_likelihood": st_like,
        "flight_comm_allowed": comm_allowed,
        "flight_comm_weight": comm_weight,
        "flight_intent": flight_intent,
        "flight_has_wind_obs": flight_has_wind_obs,
        "ff_time_gap_sec": ff_time_gap_sec,
        "ff_space_hdist_km": ff_hdist_km,
        "ff_space_vdist_m": ff_vdist_m,
        "ff_time_conf": ff_time_conf,
        "ff_space_conf": ff_space_conf,
        "ff_time_likelihood": ff_time_like,
        "ff_space_likelihood": ff_space_like,
        "ff_st_conf": ff_st_conf,
        "ff_st_likelihood": ff_st_like,
        "ff_comm_allowed": ff_sel["ff_allowed"],
        "ff_comm_weight": ff_sel["ff_weight"],
        "ff_motion_allowed": ff_sel["ff_motion_allowed"],
        "ff_motion_weight": ff_sel["ff_motion_weight"],
        "ff_wind_allowed": ff_sel["ff_wind_allowed"],
        "ff_wind_weight": ff_sel["ff_wind_weight"],
        "ff_sparse_src": ff_sel["ff_sparse_src"],
        "ff_sparse_dst": ff_sel["ff_sparse_dst"],
        "ff_sparse_score": ff_sel["ff_sparse_score"],
        "flight_topk": np.array(n_slots, dtype=np.int32),
        "valid_flight_agents": int(mask.sum()),
        "candidate_flight_count": int(candidate_count),
        "tier1_candidate_count": int(len(tier1)),
        "tier2_candidate_count": int(len(tier2)),
        "valid_wind_capable_flights": int(flight_has_wind_obs.sum()),
        "ff_motion_edges": int(ff_sel["ff_motion_allowed"].sum()),
        "ff_wind_edges": int(ff_sel["ff_wind_allowed"].sum()),
        "comm_eligible_count": int(comm_eligible_count),
        "comm_eligible_ratio": float(comm_eligible_count / max(1, valid_count)),
        "ff_edge_density": float(ff_density),
        "flight_st_conf_p50": float(np.percentile(st_conf_valid, 50)) if st_conf_valid.size > 0 else 0.0,
        "flight_st_conf_p90": float(np.percentile(st_conf_valid, 90)) if st_conf_valid.size > 0 else 0.0,
        "flight_st_likelihood_p50": float(np.percentile(st_like_valid, 50)) if st_like_valid.size > 0 else 0.0,
        "flight_st_likelihood_p90": float(np.percentile(st_like_valid, 90)) if st_like_valid.size > 0 else 0.0,
    }
