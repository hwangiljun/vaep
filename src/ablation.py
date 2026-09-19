"""설계 선택의 근거를 만드는 비교 실험 (논문 Table 3에 대응).

무엇을 비교하나
  1) 피처 집합: 아무 피처도 안 쓸 때 / 위치만 / 행동 유형만 / 둘 다 / 전체 145개
  2) 알고리즘: XGBoost(이 프로젝트 설정), 로지스틱 회귀, 랜덤 포레스트
  3) XGBoost 용량: 트리 50·깊이 3 / 100·3 / 200·4 / 300·6

평가는 모두 같은 조건에서 한다. 날짜순 앞 304경기로 학습해 마지막 76경기로 한 번 평가한다.
학습 폴드를 여러 개 돌리지 않는 이유는, 여기서 궁금한 것이 '설정 사이의 상대 비교'이고
같은 분할을 쓰면 그 비교가 공정하기 때문이다.

    python src/ablation.py            # 전부 (약 20분)
    python src/ablation.py --only holdout   # 피처·알고리즘 비교만 (약 7분)
    python src/ablation.py --only oof       # 용량 비교만 (약 12분)

    out/features.parquet, labels.parquet -> out/ablation.csv, out/capacity_oof.csv
"""
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_features import XFN_NAMES  # noqa: E402
from config import HOLDOUT_FRAC, NB_PREV_ACTIONS, OUT, SEED, XGB_PARAMS  # noqa: E402
from train import DEVICE, N_THREADS  # noqa: E402

warnings.filterwarnings("ignore")
LABELS = ["scores", "concedes"]

# 용량 비교에 쓰는 설정들. 트리 수와 깊이만 바꾸고 나머지는 XGB_PARAMS 그대로 둔다.
CAPACITIES = {
    "트리 50 · 깊이 3": dict(n_estimators=50, max_depth=3),
    "트리 100 · 깊이 3 (선택)": dict(n_estimators=100, max_depth=3),
    "트리 200 · 깊이 4": dict(n_estimators=200, max_depth=4),
    "트리 300 · 깊이 6": dict(n_estimators=300, max_depth=6),
}


def feature_subsets(all_cols):
    """논문 Table 3과 같은 피처 묶음을 만든다."""
    import socceraction.vaep.features as fs

    loc = fs.feature_column_names([fs.startlocation, fs.endlocation], NB_PREV_ACTIONS)
    typ = fs.feature_column_names([fs.actiontype_onehot], NB_PREV_ACTIONS)
    loc = [c for c in loc if c in all_cols]
    typ = [c for c in typ if c in all_cols]
    return {
        "피처 없음 (기저율)": [],
        "위치만": loc,
        "행동 유형만": typ,
        "위치 + 행동 유형": loc + typ,
        "전체 피처 (이 프로젝트)": list(all_cols),
    }


def score(y, p):
    base = np.full_like(p, y.mean(), dtype=float)
    brier, brier_base = brier_score_loss(y, p), brier_score_loss(y, base)
    out = {
        "brier": brier,
        "brier_skill": 1 - brier / brier_base,
        "log_loss": log_loss(y, p, labels=[0, 1]),
    }
    out["roc_auc"] = np.nan if p.min() == p.max() else roc_auc_score(y, p)
    return out


def make_model(kind, **kw):
    if kind == "xgb":
        import xgboost

        params = dict(XGB_PARAMS)
        params.update(kw)
        return xgboost.XGBClassifier(**params, device=DEVICE, n_jobs=N_THREADS)
    # XGBoost는 결측을 그대로 받지만 sklearn 모델은 못 받는다.
    # 좌표가 없는 행동(7개)이 있으므로 중앙값으로 채워 넣고 비교한다.
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline

    if kind == "logreg":
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        # 로지스틱 회귀는 스케일에 민감하므로 표준화를 함께 건다 (트리 모델은 불필요)
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(max_iter=1000, n_jobs=N_THREADS, random_state=SEED),
        )
    if kind == "rf":
        from sklearn.ensemble import RandomForestClassifier

        return make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=100, min_samples_leaf=10, n_jobs=N_THREADS, random_state=SEED
            ),
        )
    raise ValueError(kind)


def capacity_oof():
    """용량 비교를 최종 값 산출과 같은 프로토콜(경기 단위 5겹 OOF)로 한 번 더 한다.

    홀드아웃 한 번은 표본이 76경기라 실점처럼 드문 라벨에서는 흔들린다.
    실제로 값을 만들 때 쓰는 분할로 비교해야 선택의 근거가 된다.
    """
    from sklearn.model_selection import KFold

    from config import N_FOLDS
    from train import boot_auc_ci, evaluate

    games = pd.read_parquet(os.path.join(OUT, "games.parquet")).sort_values(["game_date", "game_id"])
    X = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    Y = pd.read_parquet(os.path.join(OUT, "labels.parquet"))
    cols = [c for c in X.columns if c not in ("game_id", "action_id")]
    gid, allg = X.game_id.to_numpy(), games.game_id.to_numpy()

    rows = []
    for name, kw in CAPACITIES.items():
        t0 = time.time()
        oof = pd.DataFrame(index=X.index, columns=LABELS, dtype=float)
        for tr_g, te_g in KFold(N_FOLDS, shuffle=True, random_state=SEED).split(allg):
            tr, te = np.isin(gid, allg[tr_g]), np.isin(gid, allg[te_g])
            for label in LABELS:
                model = make_model("xgb", **kw)
                model.fit(X.loc[tr, cols], Y.loc[tr, label])
                oof.loc[te, label] = model.predict_proba(X.loc[te, cols])[:, 1]
        for label in LABELS:
            y, p = Y[label].to_numpy().astype(int), oof[label].to_numpy()
            r = evaluate(y, p, label, name)
            r["auc_lo"], r["auc_hi"] = boot_auc_ci(y, p, gid)
            rows.append({"setting": name, **{k: v for k, v in r.items() if k != "split"}})
        print(f"  [용량·OOF] {name} 완료 ({time.time() - t0:.0f}초)", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "capacity_oof.csv"), index=False)
    print(out[["setting", "label", "brier_skill", "roc_auc", "auc_lo", "auc_hi"]]
          .to_string(index=False, float_format="%.4f"))
    print(f"저장: {OUT}/capacity_oof.csv")


def main():
    games = pd.read_parquet(os.path.join(OUT, "games.parquet")).sort_values(["game_date", "game_id"])
    X = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    Y = pd.read_parquet(os.path.join(OUT, "labels.parquet"))
    all_cols = [c for c in X.columns if c not in ("game_id", "action_id")]
    gid = X.game_id.to_numpy()

    n_train = int(len(games) * (1 - HOLDOUT_FRAC))
    tr = np.isin(gid, games.game_id.to_numpy()[:n_train])
    te = np.isin(gid, games.game_id.to_numpy()[n_train:])
    print(f"학습 {tr.sum():,}행 / 평가 {te.sum():,}행 · 장치 {DEVICE}")

    runs = []
    for name, cols in feature_subsets(all_cols).items():
        runs.append(("피처 집합", name, "xgb", {}, cols))
    full = list(all_cols)
    runs += [
        ("알고리즘", "XGBoost (이 프로젝트)", "xgb", {}, full),
        ("알고리즘", "로지스틱 회귀", "logreg", {}, full),
        ("알고리즘", "랜덤 포레스트", "rf", {}, full),
    ]
    for name, kw in CAPACITIES.items():
        runs.append(("XGBoost 용량", name, "xgb", kw, full))

    rows, t0 = [], time.time()
    for group, name, kind, kw, cols in runs:
        row = {"group": group, "setting": name, "n_features": len(cols)}
        for label in LABELS:
            y_tr, y_te = Y.loc[tr, label].to_numpy().astype(int), Y.loc[te, label].to_numpy().astype(int)
            if cols:
                model = make_model(kind, **kw)
                model.fit(X.loc[tr, cols], y_tr)
                p = model.predict_proba(X.loc[te, cols])[:, 1]
            else:
                p = np.full(te.sum(), y_tr.mean())     # 항상 학습 데이터의 평균을 찍는 기준선
            for k, v in score(y_te, p).items():
                row[f"{label}_{k}"] = v
        rows.append(row)
        print(f"  [{group}] {name}: "
              f"득점 BSS {row['scores_brier_skill']:.3f} / AUC {row['scores_roc_auc']:.3f} · "
              f"실점 BSS {row['concedes_brier_skill']:.3f} / AUC {row['concedes_roc_auc']:.3f} "
              f"({time.time() - t0:.0f}초)", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "ablation.csv"), index=False)
    print(f"\n저장: {OUT}/ablation.csv")


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "all"
    if only in ("all", "holdout"):
        main()
    if only in ("all", "oof"):
        capacity_oof()
