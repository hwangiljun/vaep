"""폴드를 다르게 나누면 선수 값이 얼마나 흔들리는지 측정한다.

선수 순위는 '그 경기를 학습에 쓰지 않은 모델'의 예측으로 만든다. 그런데 어느 경기를 어느 폴드에
넣느냐는 임의의 선택이다. 그 임의성이 값에 얼마나 영향을 주는지 알아야 순위를 어디까지 믿을지 정할 수 있다.

시드를 바꿔 5겹을 세 번 다시 나누고, 상위 선수들의 90분당 VAEP가 얼마나 달라지는지 본다.

    -> out/fold_sensitivity.csv   (약 8분)
"""
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MIN_MINUTES, N_FOLDS, OUT, SEED, XGB_PARAMS  # noqa: E402
from train import DEVICE, N_THREADS  # noqa: E402

warnings.filterwarnings("ignore")
SEEDS = [SEED, 7, 1234]
TOP_N = 12


def main():
    import socceraction.spadl as spadl
    import socceraction.vaep.formula as vf
    import xgboost

    X = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    Y = pd.read_parquet(os.path.join(OUT, "labels.parquet"))
    actions = pd.read_parquet(os.path.join(OUT, "actions.parquet"))
    games = pd.read_parquet(os.path.join(OUT, "games.parquet")).sort_values(["game_date", "game_id"])
    players = pd.read_parquet(os.path.join(OUT, "players.parquet"))
    pg = pd.read_parquet(os.path.join(OUT, "player_games.parquet"))

    cols = [c for c in X.columns if c not in ("game_id", "action_id")]
    gid, allg = X.game_id.to_numpy(), games.game_id.to_numpy()
    named = spadl.add_names(actions)
    minutes = pg.groupby("player_id").minutes_played.sum()

    res = {}
    for seed in SEEDS:
        t0 = time.time()
        oof = pd.DataFrame(index=X.index, columns=["scores", "concedes"], dtype=float)
        for tr_g, te_g in KFold(N_FOLDS, shuffle=True, random_state=seed).split(allg):
            tr, te = np.isin(gid, allg[tr_g]), np.isin(gid, allg[te_g])
            for label in ("scores", "concedes"):
                model = xgboost.XGBClassifier(**XGB_PARAMS, device=DEVICE, n_jobs=N_THREADS)
                model.fit(X.loc[tr, cols], Y.loc[tr, label])
                oof.loc[te, label] = model.predict_proba(X.loc[te, cols])[:, 1]

        values = []
        for game_id, idx in named.groupby("game_id", sort=False).groups.items():
            a = named.loc[idx].reset_index(drop=True)
            p = oof.loc[idx].reset_index(drop=True)
            values.append(vf.value(a, p["scores"], p["concedes"]).vaep_value.values)
        per_player = pd.Series(np.concatenate(values), index=named.player_id.values).groupby(level=0).sum()
        p90 = (per_player / minutes.reindex(per_player.index) * 90).dropna()
        res[f"seed_{seed}"] = p90[minutes.reindex(p90.index) >= MIN_MINUTES]
        print(f"  시드 {seed} 완료 ({time.time() - t0:.0f}초)", flush=True)

    df = pd.DataFrame(res).join(players.set_index("player_id")[["player_name", "nickname"]])
    df["name"] = df.nickname.fillna(df.player_name)
    seed_cols = [f"seed_{s}" for s in SEEDS]
    df["mean"] = df[seed_cols].mean(axis=1)
    df["spread"] = df[seed_cols].max(axis=1) - df[seed_cols].min(axis=1)
    ranks = pd.DataFrame({c: df[c].rank(ascending=False) for c in seed_cols})
    df["rank_move"] = (ranks.max(axis=1) - ranks.min(axis=1)).astype(int)
    df = df.sort_values("mean", ascending=False)
    df[["name"] + seed_cols + ["mean", "spread", "rank_move"]].to_csv(
        os.path.join(OUT, "fold_sensitivity.csv"), index=False)

    top = df.head(TOP_N)
    print(top[["name"] + seed_cols + ["mean", "spread", "rank_move"]]
          .to_string(index=False, float_format="%.3f"))
    print(f"\n상위 {TOP_N}명 흔들림(최대-최소): 중앙값 {top.spread.median():.3f}, 최대 {top.spread.max():.3f}")
    print(f"상위 10명의 순위 변동: 최대 {int(df.head(10).rank_move.max())}계단")
    print(f"저장: {OUT}/fold_sensitivity.csv")


if __name__ == "__main__":
    main()
