"""보고서용 흑백 그림을 만든다.

보고서는 검정색만 쓰기로 했으므로, 노트북의 컬러 그림과 같은 내용을
회색 명암과 선 모양(실선/점선)·해칭으로 구분한 판을 따로 만든다.

    -> figures/report/*.png
"""
import os
import sys

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style  # noqa: E402
import viz  # noqa: E402
from config import FIG, MIN_MINUTES, OUT  # noqa: E402

# 색 역할만 회색 명암으로 바꾼다. 나머지 그리는 코드는 노트북과 같다.
style.BLUE, style.ORANGE, style.AQUA, style.RED = "#101010", "#6e6e6e", "#303030", "#9a9a9a"
style.INK, style.INK2, style.MUTED = "#000000", "#333333", "#666666"
style.GRID, style.BASE, style.SURF = "#dcdcdc", "#b0b0b0", "#ffffff"
style.PITCH_LINE = "#b0b0b0"
viz.SEQ_COLORS = ["#d9d9d9", "#7a7a7a", "#101010"]

OUTDIR = os.path.join(FIG, "report")
os.makedirs(OUTDIR, exist_ok=True)


def save(fig, name):
    path = os.path.join(OUTDIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    print("  ", path)


def fig_model_eval():
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import roc_curve

    Y = pd.read_parquet(f"{OUT}/labels.parquet")
    preds = pd.read_parquet(f"{OUT}/predictions.parquet")
    hold = pd.read_parquet(f"{OUT}/predictions_holdout.parquet")
    Yh = Y.set_index(["game_id", "action_id"]).loc[
        pd.MultiIndex.from_frame(hold[["game_id", "action_id"]])].reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    cal = []
    for label, color in [("scores", "#101010"), ("concedes", "#7a7a7a")]:
        for yy, pp, ls, tag in [(Y[label], preds[label], "-", "OOF"),
                                (Yh[label], hold[label], "--", "홀드아웃")]:
            fpr, tpr, _ = roc_curve(yy, pp)
            step = max(1, len(fpr) // 2000)
            name = "득점" if label == "scores" else "실점"
            axes[0].plot(fpr[::step], tpr[::step], ls, color=color, lw=1.7, label=f"{name} {tag}")
            frac, mean = calibration_curve(yy, pp, n_bins=10, strategy="quantile")
            axes[1].plot(mean, frac, ls, marker="o", ms=4, color=color, lw=1.5, label=f"{name} {tag}")
            cal += [mean.max(), frac.max()]
    axes[0].plot([0, 1], [0, 1], color="#b0b0b0", lw=1)
    axes[0].set_xlabel("거짓 양성 비율"); axes[0].set_ylabel("참 양성 비율")
    axes[0].set_title("(a) ROC 곡선", loc="left"); axes[0].legend(fontsize=8.5)
    lim = max(cal) * 1.15
    axes[1].plot([0, lim], [0, lim], color="#b0b0b0", lw=1)
    axes[1].set_xlim(0, lim); axes[1].set_ylim(0, lim)
    axes[1].set_xlabel("예측 확률 (10분위 평균)"); axes[1].set_ylabel("실제 발생 비율")
    axes[1].set_title("(b) 캘리브레이션 — 대각선에 붙을수록 확률 크기가 정확", loc="left", fontsize=10)
    axes[1].legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "model_eval.png")


def fig_importance():
    import matplotlib.pyplot as plt

    imp = pd.read_csv(f"{OUT}/feature_importance.csv", index_col="feature")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    for ax, (col, title, shade) in zip(axes, [("scores", "(a) 득점 확률 모델", "#101010"),
                                              ("concedes", "(b) 실점 확률 모델", "#6e6e6e")]):
        top = imp[col].sort_values(ascending=False).head(15)[::-1]
        ax.barh(top.index, top.values, color=shade, height=0.65)
        ax.set_title(title, loc="left"); ax.tick_params(labelsize=8); ax.grid(axis="y", alpha=0)
        ax.set_xlabel("gain — 이 피처로 가른 만큼의 이득 합", fontsize=9)
    fig.tight_layout()
    save(fig, "feature_importance.png")


def fig_by_actiontype():
    import matplotlib.pyplot as plt

    bt = pd.read_csv(f"{OUT}/value_by_actiontype.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2))
    top = bt.nlargest(14, "n").sort_values("vaep_mean")
    axes[0].barh(top.type_name, top.vaep_mean, color="#303030", height=0.65)
    axes[0].set_title("(a) 행동 1회당 평균 VAEP", loc="left"); axes[0].grid(axis="y", alpha=0)
    tot = bt.nlargest(14, "n").sort_values("vaep_sum")
    axes[1].barh(tot.type_name, tot.vaep_sum, color="#101010", height=0.65)
    axes[1].set_title("(b) 시즌 전체 VAEP 합계", loc="left"); axes[1].grid(axis="y", alpha=0)
    fig.tight_layout()
    save(fig, "value_by_actiontype.png")


def fig_top_players():
    import matplotlib.pyplot as plt

    r = pd.read_csv(f"{OUT}/player_ratings.csv")
    t = r[r.minutes >= MIN_MINUTES].nlargest(10, "vaep_p90").sort_values("vaep_p90")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.barh(t.name, t.vaep_p90, color="#101010", height=0.62)
    for y, row in enumerate(t.itertuples()):
        ax.text(row.vaep_p90 + 0.012, y,
                f"{row.vaep_p90:.3f}    공격 {row.offensive_p90:+.3f} · 수비 {row.defensive_p90:+.3f}"
                f" · {row.minutes:,.0f}분",
                va="center", fontsize=8.5, color="#333333")
    ax.set_xlabel("90분당 VAEP"); ax.grid(axis="y", alpha=0)
    ax.set_xlim(0, t.vaep_p90.max() * 1.62)
    fig.tight_layout()
    save(fig, "top_players.png")


def fig_sequence():
    seq = pd.read_csv(f"{OUT}/sequence.csv")
    games = pd.read_parquet(f"{OUT}/games.parquet")
    teams = pd.read_parquet(f"{OUT}/teams.parquet").set_index("team_id").team_name
    g = games[games.game_id == seq.game_id.iloc[0]].iloc[0]
    minute = int(seq.time_seconds.iloc[-1] // 60) + (45 if seq.period_id.iloc[-1] == 2 else 0)
    title = (f"{teams[g.home_team_id]} {g.home_score}-{g.away_score} {teams[g.away_team_id]}"
             f"  ({g.game_date:%Y-%m-%d})  ·  {seq.team_name.iloc[0]}의 {minute}분 득점 장면")
    fig = viz.plot_sequence(seq, title, pscore=seq.p_scores.values)
    save(fig, "sequence.png")


def fig_traditional():
    """전통 지표 순위 vs VAEP 순위 산점도."""
    import matplotlib.pyplot as plt

    d = pd.read_csv(f"{OUT}/traditional_vs_vaep.csv")
    fig, ax = plt.subplots(figsize=(7.2, 5.6))
    ax.scatter(d.rank_ga_p90, d.rank_vaep_p90, s=14, color="#101010", alpha=0.45,
               edgecolors="none")
    lim = len(d) + 5
    ax.plot([0, lim], [0, lim], color="#b0b0b0", lw=1)
    label_me = pd.concat([d.nsmallest(6, "rank_vaep_p90"), d.nsmallest(5, "rank_ga_p90")]).drop_duplicates("player_id")
    for row in label_me.itertuples():
        ax.annotate(row.name, (row.rank_ga_p90, row.rank_vaep_p90), fontsize=8,
                    color="#000000", xytext=(5, 4), textcoords="offset points")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.invert_xaxis(); ax.invert_yaxis()
    ax.set_xlabel("90분당 골+어시스트 순위 (1위가 오른쪽 아래)")
    ax.set_ylabel("90분당 VAEP 순위")
    ax.set_title(f"두 지표의 순위 비교 (900분 이상 {len(d)}명, 스피어만 "
                 f"{d.ga_p90.corr(d.vaep_p90, method='spearman'):.2f})", loc="left", fontsize=10.5)
    fig.tight_layout()
    save(fig, "traditional_vs_vaep.png")


def main():
    style.use()
    print("보고서용 흑백 그림 생성")
    fig_model_eval()
    fig_importance()
    fig_by_actiontype()
    fig_top_players()
    fig_sequence()
    fig_traditional()


if __name__ == "__main__":
    main()
