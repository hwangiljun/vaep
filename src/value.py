"""VAEP 공식으로 행동마다 공격 가치·수비 가치·VAEP 값을 계산하고 선수 랭킹을 만든다.

    공격 가치 = 이 행동으로 우리 팀의 득점 확률이 얼마나 올랐나
    수비 가치 = 이 행동으로 우리 팀의 실점 확률이 얼마나 내렸나
    VAEP     = 공격 가치 + 수비 가치

확률은 학습에 쓰이지 않은 모델이 예측한 값(out/predictions.parquet)을 쓴다.

    -> out/action_values.parquet, out/player_ratings.csv, out/value_by_actiontype.csv
"""
import os
import sys
import warnings

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MIN_MINUTES, OUT  # noqa: E402

warnings.filterwarnings("ignore")


def main():
    import socceraction.spadl as spadl
    import socceraction.vaep.formula as vaepformula

    actions = pd.read_parquet(os.path.join(OUT, "actions.parquet"))
    preds = pd.read_parquet(os.path.join(OUT, "predictions.parquet"))
    players = pd.read_parquet(os.path.join(OUT, "players.parquet"))
    player_games = pd.read_parquet(os.path.join(OUT, "player_games.parquet"))
    teams = pd.read_parquet(os.path.join(OUT, "teams.parquet"))

    # 행동과 예측이 같은 순서인지 확인한 뒤 붙인다
    assert (actions.game_id.values == preds.game_id.values).all()
    assert (actions.action_id.values == preds.action_id.values).all()
    named = spadl.add_names(actions)

    values = []
    for game_id, idx in named.groupby("game_id", sort=False).groups.items():
        a = named.loc[idx].reset_index(drop=True)
        p = preds.loc[idx].reset_index(drop=True)
        v = vaepformula.value(a, p["scores"], p["concedes"])
        v.insert(0, "action_id", a.action_id.values)
        v.insert(0, "game_id", game_id)
        values.append(v)
    values = pd.concat(values).reset_index(drop=True)
    values.to_parquet(os.path.join(OUT, "action_values.parquet"))

    av = named.merge(values, on=["game_id", "action_id"])

    # 행동 유형별 요약
    by_type = (
        av.groupby("type_name")
        .agg(n=("vaep_value", "size"),
             offensive_mean=("offensive_value", "mean"),
             defensive_mean=("defensive_value", "mean"),
             vaep_mean=("vaep_value", "mean"),
             vaep_sum=("vaep_value", "sum"))
        .sort_values("vaep_sum", ascending=False)
    )
    by_type.to_csv(os.path.join(OUT, "value_by_actiontype.csv"))

    # 선수별 합계와 90분당 값
    per_player = (
        av.groupby("player_id")
        .agg(actions=("vaep_value", "size"),
             offensive=("offensive_value", "sum"),
             defensive=("defensive_value", "sum"),
             vaep=("vaep_value", "sum"))
        .reset_index()
    )
    minutes = (
        player_games.groupby("player_id")
        .agg(games=("game_id", "nunique"), minutes=("minutes_played", "sum"))
        .reset_index()
    )
    # 팀은 그 선수가 가장 많이 뛴 팀으로 적는다 (시즌 중 이적 대비)
    main_team = (
        player_games.groupby(["player_id", "team_id"])["minutes_played"].sum()
        .reset_index().sort_values("minutes_played").drop_duplicates("player_id", keep="last")
        [["player_id", "team_id"]]
    )
    ratings = (
        per_player.merge(minutes, on="player_id")
        .merge(main_team, on="player_id")
        .merge(players, on="player_id")
        .merge(teams, on="team_id")
    )
    ratings["name"] = ratings.nickname.fillna(ratings.player_name)
    ratings["vaep_p90"] = ratings.vaep / ratings.minutes * 90
    ratings["offensive_p90"] = ratings.offensive / ratings.minutes * 90
    ratings["defensive_p90"] = ratings.defensive / ratings.minutes * 90
    ratings = ratings[
        ["player_id", "name", "player_name", "team_name", "games", "minutes", "actions",
         "offensive", "defensive", "vaep", "offensive_p90", "defensive_p90", "vaep_p90"]
    ].sort_values("vaep_p90", ascending=False)
    ratings.to_csv(os.path.join(OUT, "player_ratings.csv"), index=False)

    top = ratings[ratings.minutes >= MIN_MINUTES].head(10)
    print(f"행동 {len(values):,}개의 VAEP 계산 완료 (합계 {values.vaep_value.sum():.0f})")
    print(f"\n90분당 VAEP 상위 10명 ({MIN_MINUTES}분 이상 출전, {len(ratings[ratings.minutes >= MIN_MINUTES])}명 중)")
    print(top[["name", "team_name", "minutes", "vaep", "vaep_p90"]]
          .to_string(index=False, float_format="%.2f"))
    print(f"\n저장: {OUT}/action_values.parquet, player_ratings.csv, value_by_actiontype.csv")


if __name__ == "__main__":
    main()
