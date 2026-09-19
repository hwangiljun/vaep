"""한 번의 공격이 진행되는 동안 행동마다 VAEP가 어떻게 변하는지 그린다.

골로 끝난 공격 중에서 '연속된 같은 팀 행동'이 가장 길고 VAEP 합이 큰 장면을 하나 고른다.

    -> figures/sequence.png, out/sequence.csv
"""
import os
import sys

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.patches import Arc, Rectangle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style  # noqa: E402
from config import FIG, OUT  # noqa: E402

LENGTH, WIDTH = 105.0, 68.0   # SPADL 경기장 크기 (m)

# 화살표 색 눈금 (VAEP가 클수록 뒤쪽 색). 흑백 보고서용으로 바꿔 끼울 수 있게 밖에 둔다.
SEQ_COLORS = ["#f3d9a4", "#eb6834", "#8c1d1d"]


def draw_pitch(ax):
    """SPADL 좌표계(105x68) 위에 경기장을 그린다. 왼쪽 -> 오른쪽 공격."""
    ax.set_xlim(-3, LENGTH + 3)
    ax.set_ylim(-3, WIDTH + 3)
    ax.set_aspect("equal")
    ax.axis("off")
    line = dict(color=style.PITCH_LINE, lw=1.2, zorder=1)
    ax.add_patch(Rectangle((0, 0), LENGTH, WIDTH, fill=False, **line))
    ax.plot([LENGTH / 2, LENGTH / 2], [0, WIDTH], **line)
    ax.add_patch(Arc((LENGTH / 2, WIDTH / 2), 18.3, 18.3, **line))
    for x0, side in ((0, 1), (LENGTH, -1)):
        # 페널티 박스 16.5m x 40.32m, 골 에어리어 5.5m x 18.32m
        ax.add_patch(Rectangle((x0 if side > 0 else x0 - 16.5, (WIDTH - 40.32) / 2),
                               16.5, 40.32, fill=False, **line))
        ax.add_patch(Rectangle((x0 if side > 0 else x0 - 5.5, (WIDTH - 18.32) / 2),
                               5.5, 18.32, fill=False, **line))
        ax.add_patch(Rectangle((x0 if side > 0 else x0 - 2.0, (WIDTH - 7.32) / 2),
                               2.0, 7.32, fill=False, **line))
        ax.plot([x0 + side * 11], [WIDTH / 2], marker=".", color=style.PITCH_LINE, zorder=1)


def select_sequence(av, min_len=6, max_gap=15.0, max_len=10):
    """골로 끝난 공격 중 가장 볼 만한 장면 하나를 고른다.

    같은 팀이 연속으로 한 행동만 이어 붙이고, 행동 사이 간격이 max_gap초를 넘으면 끊는다.
    페널티킥으로 끝난 장면은 제외한다.
    """
    goals = av[(av.type_name.str.contains("shot"))
               & (av.result_name == "success")
               & (av.type_name != "shot_penalty")]
    best = None
    for g in goals.itertuples():
        game = av[av.game_id == g.game_id]
        pos = game.index.get_loc(g.Index)
        rows = [g.Index]
        for j in range(pos - 1, max(pos - max_len, -1), -1):
            prev, cur = game.iloc[j], game.loc[rows[-1]]
            if prev.team_id != g.team_id or prev.period_id != g.period_id:
                break
            if cur.time_seconds - prev.time_seconds > max_gap:
                break
            rows.append(game.index[j])
        seq = av.loc[sorted(rows)]
        if len(seq) < min_len:
            continue
        score = (len(seq), seq.vaep_value.sum())
        if best is None or score > best[0]:
            best = (score, seq)
    if best is None:
        raise RuntimeError("조건에 맞는 공격 장면을 찾지 못했다")
    return best[1]


def plot_sequence(seq, title="", pscore=None):
    """위: 경기장 위의 행동 흐름 / 아래: 행동별 VAEP 막대와 득점 확률."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    style.use()
    fig = plt.figure(figsize=(11, 8.4))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.5, 1], hspace=0.16)
    ax = fig.add_subplot(gs[0])
    draw_pitch(ax)

    # VAEP가 클수록 진한 색. 작은 값도 보이도록 옅은 쪽을 너무 밝지 않게 잡는다.
    cmap = LinearSegmentedColormap.from_list("vaep", SEQ_COLORS)
    vmax = max(seq.vaep_value.max(), 1e-6)
    drawn = []
    for i, (_, a) in enumerate(seq.iterrows(), 1):
        col = cmap(max(a.vaep_value, 0) / vmax)
        is_shot = "shot" in a.type_name
        ax.annotate("", xy=(a.end_x, a.end_y), xytext=(a.start_x, a.start_y),
                    arrowprops=dict(arrowstyle="-|>,head_width=0.3,head_length=0.7",
                                    color=col, lw=3.2 if is_shot else 2.2,
                                    shrinkA=0, shrinkB=0, alpha=0.95), zorder=3)
        # 같은 자리에서 연달아 일어난 행동은 번호가 겹치므로 옆으로 조금 밀어 선으로 잇는다
        bx, by = a.start_x, a.start_y
        near = sum((bx - px) ** 2 + (by - py) ** 2 < 2.6 ** 2 for px, py in drawn)
        if near:
            ux, uy = a.end_x - a.start_x, a.end_y - a.start_y
            norm = (ux ** 2 + uy ** 2) ** 0.5 or 1.0
            bx, by = bx - uy / norm * 3.0 * near, by + ux / norm * 3.0 * near
            ax.plot([a.start_x, bx], [a.start_y, by], "-", color=style.MUTED, lw=0.7, zorder=3)
        drawn.append((a.start_x, a.start_y))
        ax.plot(bx, by, "o", ms=15, color=style.SURF,
                markeredgecolor=col, markeredgewidth=2, zorder=4)
        ax.text(bx, by, str(i), ha="center", va="center",
                fontsize=8.5, color=style.INK, zorder=5)
    last = seq.iloc[-1]
    ax.plot(last.end_x, last.end_y, "*", ms=20, color=SEQ_COLORS[-1], zorder=6)
    ax.annotate("공격 방향", xy=(LENGTH * 0.62, -1.6), xytext=(LENGTH * 0.46, -1.6),
                fontsize=8.5, color=style.MUTED, va="center",
                arrowprops=dict(arrowstyle="-|>", color=style.MUTED, lw=1))
    ax.text(LENGTH / 2, WIDTH + 1.5, "번호는 행동 순서, 색이 진할수록 VAEP가 크다. ★는 골.",
            ha="center", va="bottom", fontsize=8.5, color=style.MUTED)
    ax.set_title(title, fontsize=12, pad=16, loc="left")

    ax2 = fig.add_subplot(gs[1])
    n = len(seq)
    x = np.arange(1, n + 1)
    colors = [style.AQUA if v >= 0 else style.RED for v in seq.vaep_value]
    ax2.bar(x, seq.vaep_value, color=colors, width=0.62, zorder=3)
    span = seq.vaep_value.max() - min(seq.vaep_value.min(), 0)
    for xi, v in zip(x, seq.vaep_value):
        ax2.text(xi, v + (0.02 if v >= 0 else -0.02) * span, f"{v:+.3f}",
                 ha="center", va="bottom" if v >= 0 else "top", fontsize=8, color=style.INK2)
    ax2.axhline(0, color=style.BASE, lw=1)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{i}. {t}\n{short_name(p)}" for i, (t, p) in
                         enumerate(zip(seq.type_name, seq["name"]), 1)], fontsize=8.5)
    ax2.set_ylabel("행동의 VAEP")
    ax2.set_ylim(min(seq.vaep_value.min() * 1.5, -0.03 * span), seq.vaep_value.max() * 1.3)

    if pscore is not None:
        ax3 = ax2.twinx()
        ax3.plot(x, pscore, "-o", color=style.BLUE, ms=4.5, lw=1.8, zorder=4)
        ax3.set_ylabel("직후 득점 확률", color=style.BLUE)
        ax3.tick_params(axis="y", colors=style.BLUE)
        ax3.grid(False)
        ax3.set_ylim(0, min(1.0, max(pscore) * 1.15))
    return fig


def short_name(name):
    """'Pablo Hernández' -> 'P. Hernández' (x축 라벨이 겹치지 않게)."""
    parts = str(name).split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else str(name)


def load_actions_with_values():
    """행동 + VAEP 값 + 선수/팀 이름 + 득점확률 예측을 한 표로 합친다."""
    import socceraction.spadl as spadl

    actions = pd.read_parquet(os.path.join(OUT, "actions.parquet"))
    values = pd.read_parquet(os.path.join(OUT, "action_values.parquet"))
    preds = pd.read_parquet(os.path.join(OUT, "predictions.parquet"))
    players = pd.read_parquet(os.path.join(OUT, "players.parquet"))
    teams = pd.read_parquet(os.path.join(OUT, "teams.parquet"))

    av = spadl.add_names(actions).merge(values, on=["game_id", "action_id"])
    av = av.merge(preds.rename(columns={"scores": "p_scores", "concedes": "p_concedes"}),
                  on=["game_id", "action_id"])
    av = av.merge(players, on="player_id", how="left").merge(teams, on="team_id", how="left")
    av["name"] = av.nickname.fillna(av.player_name)
    return av


def main():
    matplotlib.use("Agg")
    av = load_actions_with_values()
    games = pd.read_parquet(os.path.join(OUT, "games.parquet"))
    teams = pd.read_parquet(os.path.join(OUT, "teams.parquet")).set_index("team_id").team_name

    seq = select_sequence(av)
    g = games[games.game_id == seq.game_id.iloc[0]].iloc[0]
    minute = int(seq.time_seconds.iloc[-1] // 60) + (45 if seq.period_id.iloc[-1] == 2 else 0)
    title = (f"{teams[g.home_team_id]} {g.home_score}-{g.away_score} {teams[g.away_team_id]}"
             f"  ({g.game_date:%Y-%m-%d})  ·  {seq.team_name.iloc[0]}의 {minute}분 득점 장면"
             f"  ·  VAEP 합계 {seq.vaep_value.sum():+.3f}")

    fig = plot_sequence(seq, title, pscore=seq.p_scores.values)
    path = os.path.join(FIG, "sequence.png")
    fig.savefig(path, bbox_inches="tight", dpi=150)

    cols = ["game_id", "action_id", "period_id", "time_seconds", "name", "team_name",
            "type_name", "result_name", "start_x", "start_y", "end_x", "end_y",
            "p_scores", "p_concedes", "offensive_value", "defensive_value", "vaep_value"]
    seq[cols].to_csv(os.path.join(OUT, "sequence.csv"), index=False)
    print(title)
    print(seq[["name", "type_name", "result_name", "p_scores",
               "offensive_value", "defensive_value", "vaep_value"]]
          .to_string(index=False, float_format="%.4f"))
    print(f"\n저장: {path}, {OUT}/sequence.csv")


if __name__ == "__main__":
    main()
