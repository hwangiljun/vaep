"""각 행동 뒤에 골이 나올 확률(득점·실점)을 예측하는 모델을 학습하고 평가한다.

두 가지 방식을 모두 쓴다.

  OOF  : 380경기를 경기 단위 5겹으로 나눠, 각 경기를 학습에 쓰지 않은 모델로 예측한다.
         모든 행동이 공정한 예측값을 받으므로 VAEP 값과 선수 랭킹은 이 예측을 쓴다.
  홀드아웃 : 날짜순 앞 80% 경기로 학습해 마지막 20% 경기를 한 번만 예측한다.
         '한 시즌 앞부분만 보고 뒷부분을 맞힐 수 있나'를 확인하는 최종 점검이다.

    out/features.parquet, labels.parquet
      -> out/predictions.parquet        (OOF 예측, VAEP 계산에 사용)
         out/predictions_holdout.parquet
         out/metrics.csv, out/feature_importance.csv
"""
import os
import subprocess
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import KFold

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import HOLDOUT_FRAC, N_FOLDS, OUT, SEED, XGB_PARAMS  # noqa: E402

LABELS = ["scores", "concedes"]
N_BOOT = 500

warnings.filterwarnings("ignore", message=".*Falling back to prediction using DMatrix.*")


def pick_device():
    """GPU가 있으면 GPU로 학습한다. 없으면 CPU로 돌아간다 (결과물 구조는 같다).

    환경변수 VAEP_DEVICE=cpu 로 강제할 수 있다.
    GPU가 여러 장이면 가장 한가한 장을 골라 CUDA_VISIBLE_DEVICES로 고정한다.
    """
    forced = os.environ.get("VAEP_DEVICE")
    if forced:
        return forced
    try:
        q = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True)
        rows = [[int(v) for v in line.split(",")] for line in q.stdout.strip().splitlines()]
        if not rows:
            return "cpu"
        idx = min(rows, key=lambda r: (r[1], r[2]))[0]
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(idx))
        import xgboost

        xgboost.XGBClassifier(n_estimators=2, tree_method="hist", device="cuda").fit(
            np.zeros((16, 2)), np.array([0, 1] * 8))
        return "cuda"
    except Exception:
        return "cpu"


DEVICE = pick_device()


# 코어가 많은 기계에서 스레드를 다 쓰면 오히려 느려진다 (80스레드일 때 폴드당 15분,
# 16스레드일 때 30초). 코어 수와 16 중 작은 쪽을 쓴다.
N_THREADS = min(16, os.cpu_count() or 1)


def fit(X, y):
    import xgboost

    model = xgboost.XGBClassifier(**XGB_PARAMS, device=DEVICE, n_jobs=N_THREADS)
    model.fit(X, y)
    return model


def evaluate(y, p, name, split):
    """확률 예측을 네 가지로 채점한다. 기저율(항상 평균값을 찍는 모델)과 비교한다."""
    base = np.full_like(p, y.mean(), dtype=float)
    brier, brier_base = brier_score_loss(y, p), brier_score_loss(y, base)
    return {
        "split": split,
        "label": name,
        "n": len(y),
        "base_rate": y.mean(),
        "brier": brier,
        "brier_base": brier_base,
        "brier_skill": 1 - brier / brier_base,       # 1에 가까울수록 좋고 0이면 기저율과 같다
        "log_loss": log_loss(y, p, labels=[0, 1]),
        "log_loss_base": log_loss(y, base, labels=[0, 1]),
        "roc_auc": roc_auc_score(y, p),
    }


class FastAUC:
    """부트스트랩용 AUC. 예측값 정렬을 한 번만 해 두고 표본마다 가중치만 바꿔 센다.

    sklearn의 roc_auc_score를 500번 부르면 매번 757,310행을 다시 정렬한다(9분).
    정렬은 한 번이면 충분하다. 같은 값을 1분 안에 구한다. 동점은 절반씩 나눠 센다.
    """

    def __init__(self, y, p):
        order = np.argsort(p, kind="mergesort")
        self.order = order
        self.y = y[order].astype(np.float64)
        p_sorted = p[order]
        self.starts = np.flatnonzero(np.r_[True, p_sorted[1:] != p_sorted[:-1]])

    def __call__(self, w):
        ws = w[self.order].astype(np.float64)
        wp = ws * self.y                      # 양성(골로 이어진 행동)의 가중치
        wn = ws - wp                          # 음성
        gp = np.add.reduceat(wp, self.starts)  # 예측값이 같은 묶음끼리 합
        gn = np.add.reduceat(wn, self.starts)
        before = np.cumsum(gn) - gn            # 이 묶음보다 예측값이 낮은 음성의 수
        npos, nneg = wp.sum(), wn.sum()
        if npos == 0 or nneg == 0:
            return np.nan
        return float(np.sum(gp * (before + 0.5 * gn)) / (npos * nneg))


def boot_auc_ci(y, p, groups, n_boot=N_BOOT, seed=SEED):
    """경기를 다시 뽑는 부트스트랩으로 AUC의 95% 구간을 구한다."""
    auc = FastAUC(y, p)
    gidx, games = pd.factorize(groups)
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n_boot):
        counts = np.bincount(rng.integers(0, len(games), len(games)), minlength=len(games))
        a = auc(counts[gidx])
        if not np.isnan(a):
            aucs.append(a)
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def main():
    games = pd.read_parquet(os.path.join(OUT, "games.parquet")).sort_values(["game_date", "game_id"])
    X = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    Y = pd.read_parquet(os.path.join(OUT, "labels.parquet"))
    feat_cols = [c for c in X.columns if c not in ("game_id", "action_id")]
    key = X[["game_id", "action_id"]].copy()
    Xv = X[feat_cols]
    game_ids = key.game_id.to_numpy()
    dev = "GPU" if DEVICE.startswith("cuda") else "CPU"
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    print(f"행동 {len(X):,}개 · 피처 {len(feat_cols)}개 · 경기 {len(games)}개"
          f" · 학습 장치 {dev}{f' #{gpu}' if dev == 'GPU' and gpu else ''}")

    rows, t0 = [], time.time()

    # --- 1) 경기 단위 5겹 교차검증: 모든 행동에 대한 OOF 예측 -------------------
    oof = pd.DataFrame(index=X.index, columns=LABELS, dtype=float)
    folds = KFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    all_games = games.game_id.to_numpy()
    for k, (tr_g, te_g) in enumerate(folds.split(all_games), 1):
        tr = np.isin(game_ids, all_games[tr_g])
        te = np.isin(game_ids, all_games[te_g])
        for label in LABELS:
            model = fit(Xv[tr], Y.loc[tr, label])
            oof.loc[te, label] = model.predict_proba(Xv[te])[:, 1]
        print(f"  폴드 {k}/{N_FOLDS} 완료 ({time.time() - t0:.0f}초)", flush=True)

    for label in LABELS:
        y, p = Y[label].to_numpy().astype(int), oof[label].to_numpy()
        m = evaluate(y, p, label, "oof")
        m["auc_lo"], m["auc_hi"] = boot_auc_ci(y, p, game_ids)
        rows.append(m)

    pd.concat([key, oof], axis=1).to_parquet(os.path.join(OUT, "predictions.parquet"))

    # --- 2) 날짜순 홀드아웃: 앞 80% 학습 -> 마지막 20% 한 번만 평가 -------------
    n_train = int(len(games) * (1 - HOLDOUT_FRAC))
    train_games, test_games = games.game_id.to_numpy()[:n_train], games.game_id.to_numpy()[n_train:]
    tr, te = np.isin(game_ids, train_games), np.isin(game_ids, test_games)
    print(f"홀드아웃: 학습 {len(train_games)}경기 / 평가 {len(test_games)}경기"
          f" ({games.game_date.iloc[n_train]:%Y-%m-%d} 이후)")

    hold = pd.DataFrame(index=X.index[te], columns=LABELS, dtype=float)
    importance = {}
    for label in LABELS:
        model = fit(Xv[tr], Y.loc[tr, label])
        hold[label] = model.predict_proba(Xv[te])[:, 1]
        y, p = Y.loc[te, label].to_numpy().astype(int), hold[label].to_numpy()
        m = evaluate(y, p, label, "holdout")
        m["auc_lo"], m["auc_hi"] = boot_auc_ci(y, p, game_ids[te])
        rows.append(m)
        importance[label] = pd.Series(
            model.get_booster().get_score(importance_type="gain")
        ).reindex(feat_cols).fillna(0)
        print(f"  홀드아웃 {label} 완료 ({time.time() - t0:.0f}초)", flush=True)

    pd.concat([key[te], hold], axis=1).to_parquet(os.path.join(OUT, "predictions_holdout.parquet"))

    metrics = pd.DataFrame(rows)
    metrics.to_csv(os.path.join(OUT, "metrics.csv"), index=False)
    imp = pd.DataFrame(importance)
    imp.index.name = "feature"
    imp.to_csv(os.path.join(OUT, "feature_importance.csv"))

    print()
    print(metrics[["split", "label", "base_rate", "brier", "brier_skill", "log_loss",
                   "roc_auc", "auc_lo", "auc_hi"]].to_string(index=False, float_format="%.4f"))
    print(f"\n저장: {OUT}/predictions.parquet, metrics.csv, feature_importance.csv")


if __name__ == "__main__":
    main()
