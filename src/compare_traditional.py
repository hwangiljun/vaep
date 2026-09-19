"""전통 지표(골·어시스트)와 VAEP 순위를 비교한다 (논문 Table 1에 대응).

어시스트는 SPADL에 따로 없으므로 '골로 이어진 직전 같은 팀 패스/크로스'로 정의한다.
StatsBomb 원본의 공식 어시스트 표기와 완전히 같지는 않지만, 같은 데이터에서
같은 규칙으로 계산하므로 VAEP 순위와의 비교에는 무리가 없다.

    -> out/traditional_vs_vaep.csv
"""
import os
import sys
import warnings

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MIN_MINUTES, OUT  # noqa: E402

warnings.filterwarnings("ignore")
PASS_LIKE = ["pass", "cross", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short"]


def main():
    import socceraction.spadl as spadl

    actions = spadl.add_names(pd.read_parquet(os.path.join(OUT, "actions.parquet")))
    ratings = pd.read_csv(os.path.join(OUT, "player_ratings.csv"))

    # 골: 슛 계열의 성공 (자책골 제외)
    is_goal = actions.type_name.str.contains("shot") & (actions.result_name == "success")
    goals = actions[is_goal].groupby("player_id").size().rename("goals")

    # 어시스트: 골 바로 앞 행동이 같은 팀의 성공한 패스 계열이면 그 선수에게 준다
    prev = actions.shift(1)
    assist_idx = (
        is_goal
        & (prev.game_id == actions.game_id)
        & (prev.team_id == actions.team_id)
        & (prev.player_id != actions.player_id)
        & prev.type_name.isin(PASS_LIKE)
        & (prev.result_name == "success")
    )
    assists = prev[assist_idx].groupby("player_id").size().rename("assists")

    df = ratings.merge(goals, on="player_id", how="left").merge(assists, on="player_id", how="left")
    df[["goals", "assists"]] = df[["goals", "assists"]].fillna(0)
    df["goals_p90"] = df.goals / df.minutes * 90
    df["assists_p90"] = df.assists / df.minutes * 90
    df["ga_p90"] = df.goals_p90 + df.assists_p90

    elig = df[df.minutes >= MIN_MINUTES].copy()
    for col in ["goals_p90", "assists_p90", "ga_p90", "vaep_p90"]:
        elig[f"rank_{col}"] = elig[col].rank(ascending=False, method="min").astype(int)
    elig = elig.sort_values("vaep_p90", ascending=False)
    elig.to_csv(os.path.join(OUT, "traditional_vs_vaep.csv"), index=False)

    cols = ["name", "team_name", "minutes", "goals", "assists", "goals_p90", "assists_p90",
            "ga_p90", "vaep_p90", "rank_goals_p90", "rank_assists_p90", "rank_ga_p90"]
    print(f"{MIN_MINUTES}분 이상 {len(elig)}명 · 골 {int(elig.goals.sum())} · 어시스트 {int(elig.assists.sum())}")
    print("\nVAEP 상위 10명과 전통 지표 순위")
    print(elig.head(10)[cols].to_string(index=False, float_format="%.3f"))
    print("\n골+어시스트 상위 10명의 VAEP 순위")
    top_ga = elig.nlargest(10, "ga_p90")
    print(top_ga[["name", "team_name", "ga_p90", "vaep_p90", "rank_ga_p90"]]
          .assign(rank_vaep=lambda d: elig.vaep_p90.rank(ascending=False, method="min")[d.index].astype(int))
          .to_string(index=False, float_format="%.3f"))
    print(f"\n순위 상관(스피어만): 골+어시스트 vs VAEP = {elig.ga_p90.corr(elig.vaep_p90, method='spearman'):.3f}")
    print(f"저장: {OUT}/traditional_vs_vaep.csv")


if __name__ == "__main__":
    main()
