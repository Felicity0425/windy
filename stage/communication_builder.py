import numpy as np


def select_ff_edges(
    comm_round,
    ff_allowed,
    ff_score,
    flight_has_wind_obs,
    max_neighbors_per_agent,
):
    """Select air-air communication edges.

    - comm_round == 0: full connect within physically allowed edges.
    - comm_round >= 1: demand/confidence-scored sparse top-k neighbors per node.
    """
    n_slots = ff_allowed.shape[0]

    ff_sparse_src, ff_sparse_dst, ff_sparse_score = [], [], []

    if int(comm_round) == 0:
        for i in range(n_slots):
            cand_j = np.where(ff_allowed[i] > 0)[0]
            for j in cand_j:
                ff_sparse_src.append(int(i))
                ff_sparse_dst.append(int(j))
                ff_sparse_score.append(float(ff_score[i, j]))
    else:
        k_neighbors = max(1, int(max_neighbors_per_agent))
        for i in range(n_slots):
            cand_j = np.where(ff_allowed[i] > 0)[0]
            if cand_j.size == 0:
                continue
            order = np.argsort(-ff_score[i, cand_j])
            pick = cand_j[order[:k_neighbors]]
            for j in pick:
                ff_sparse_src.append(int(i))
                ff_sparse_dst.append(int(j))
                ff_sparse_score.append(float(ff_score[i, j]))

    ff_sparse_src = np.asarray(ff_sparse_src, dtype=np.int32)
    ff_sparse_dst = np.asarray(ff_sparse_dst, dtype=np.int32)
    ff_sparse_score = np.asarray(ff_sparse_score, dtype=np.float32)

    ff_allowed_out = np.zeros_like(ff_allowed, dtype=np.float32)
    ff_weight_out = np.zeros_like(ff_allowed, dtype=np.float32)
    ff_motion_allowed = np.zeros_like(ff_allowed, dtype=np.float32)
    ff_motion_weight = np.zeros_like(ff_allowed, dtype=np.float32)
    ff_wind_allowed = np.zeros_like(ff_allowed, dtype=np.float32)
    ff_wind_weight = np.zeros_like(ff_allowed, dtype=np.float32)

    for s, d, sc in zip(ff_sparse_src, ff_sparse_dst, ff_sparse_score):
        ff_allowed_out[s, d] = 1.0
        ff_weight_out[s, d] = sc
        ff_motion_allowed[s, d] = 1.0
        ff_motion_weight[s, d] = sc
        # 风边采用“强/弱激活”两级策略：
        # - 双端都具备风能力：强风边（1.0）
        # - 只有一端具备风能力：弱风边（0.5），表示可传播但可信度较低
        # - 双端都没有风能力：不建风边
        both_wind = 1.0 if (flight_has_wind_obs[s] > 0 and flight_has_wind_obs[d] > 0) else 0.0
        one_wind = 1.0 if ((flight_has_wind_obs[s] > 0) ^ (flight_has_wind_obs[d] > 0)) else 0.0
        wind_gate = both_wind + 0.5 * one_wind
        ff_wind_allowed[s, d] = wind_gate
        ff_wind_weight[s, d] = sc * wind_gate

    return {
        "ff_sparse_src": ff_sparse_src,
        "ff_sparse_dst": ff_sparse_dst,
        "ff_sparse_score": ff_sparse_score,
        "ff_allowed": ff_allowed_out,
        "ff_weight": ff_weight_out,
        "ff_motion_allowed": ff_motion_allowed,
        "ff_motion_weight": ff_motion_weight,
        "ff_wind_allowed": ff_wind_allowed,
        "ff_wind_weight": ff_wind_weight,
    }
