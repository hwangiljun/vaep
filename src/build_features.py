"""SPADL 행동에서 VAEP 모델의 입력 피처와 라벨을 만든다.

    out/actions.parquet  ->  out/features.parquet, out/labels.parquet

피처는 '게임 상태' 단위로 만든다. 게임 상태 = 지금 행동 + 직전 2개 행동(a0,a1,a2).
공격 방향은 모두 왼쪽에서 오른쪽으로 맞춘 뒤 계산한다.

라벨은 각 행동 시점에서
    scores   : 이후 10개 행동 안에 공을 가진 팀이 골을 넣었는가
    concedes : 이후 10개 행동 안에 공을 가진 팀이 골을 먹었는가
"""
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import NB_PREV_ACTIONS, OUT  # noqa: E402

warnings.filterwarnings("ignore")
N_WORKERS = 16

# 모델에 들어가는 피처 (VAEP 논문과 socceraction 공개 노트북의 구성)
XFN_NAMES = [
    "actiontype_onehot",   # 행동 유형 (패스, 드리블, 슛, 태클, ...)
    "bodypart_onehot",     # 발/머리/기타
    "result_onehot",       # 성공/실패/오프사이드/자책골
    "goalscore",           # 현재 스코어와 골 차
    "startlocation",       # 시작 좌표
    "endlocation",         # 끝 좌표
    "movement",            # 이동 거리 (dx, dy, 직선거리)
    "space_delta",         # 직전 행동과의 위치 차이
    "startpolar",          # 시작점에서 골대까지 거리·각도
    "endpolar",            # 끝점에서 골대까지 거리·각도
    "team",                # 직전 행동이 같은 팀인지
    "time_delta",          # 직전 행동과의 시간 차이
]
YFN_NAMES = ["scores", "concedes"]


def xfns():
    import socceraction.vaep.features as fs

    return [getattr(fs, n) for n in XFN_NAMES]


def yfns():
    import socceraction.vaep.labels as lab

    return [getattr(lab, n) for n in YFN_NAMES]


def one_game(args):
    """경기 하나의 피처와 라벨."""
    import socceraction.spadl as spadl
    import socceraction.vaep.features as fs

    game_id, home_team_id, actions = args
    named = spadl.add_names(actions)

    gs = fs.gamestates(named, NB_PREV_ACTIONS)
    gs = fs.play_left_to_right(gs, home_team_id)
    X = pd.concat([fn(gs) for fn in xfns()], axis=1)
    Y = pd.concat([fn(named) for fn in yfns()], axis=1)

    key = actions[["game_id", "action_id"]].reset_index(drop=True)
    X = pd.concat([key, X.reset_index(drop=True)], axis=1)
    Y = pd.concat([key, Y.reset_index(drop=True)], axis=1)
    return X, Y


def main():
    games = pd.read_parquet(os.path.join(OUT, "games.parquet"))
    actions = pd.read_parquet(os.path.join(OUT, "actions.parquet"))
    by_game = dict(list(actions.groupby("game_id", sort=False)))

    jobs = [(g.game_id, g.home_team_id, by_game[g.game_id]) for g in games.itertuples()]
    t0, Xs, Ys = time.time(), [], []
    with ProcessPoolExecutor(max_workers=N_WORKERS) as ex:
        for i, (X, Y) in enumerate(ex.map(one_game, jobs, chunksize=4), 1):
            Xs.append(X)
            Ys.append(Y)
            if i % 50 == 0 or i == len(jobs):
                print(f"  피처·라벨 {i}/{len(jobs)}경기 ({time.time() - t0:.0f}초)", flush=True)

    X = pd.concat(Xs).reset_index(drop=True)
    Y = pd.concat(Ys).reset_index(drop=True)
    assert len(X) == len(actions) and len(Y) == len(actions)

    X.to_parquet(os.path.join(OUT, "features.parquet"))
    Y.to_parquet(os.path.join(OUT, "labels.parquet"))

    feat_cols = [c for c in X.columns if c not in ("game_id", "action_id")]
    print(f"피처 {len(feat_cols)}개 x {len(X):,}행")
    for c in YFN_NAMES:
        print(f"  {c}: {Y[c].mean() * 100:.2f}% ({int(Y[c].sum()):,}개)")
    print(f"저장: {OUT}/features.parquet, {OUT}/labels.parquet")


if __name__ == "__main__":
    main()
