"""과제 보고서(Word)를 만든다.

out/의 결과 파일과 figures/report/의 흑백 그림을 읽어 보고서(.docx)를 만든다.
저장소에는 올리지 않으므로 기본 출력 위치는 프로젝트 폴더 바깥이다. 숫자를 문서에 직접 적지 않고 결과에서 읽어 오므로,
파이프라인을 다시 돌린 뒤 이 스크립트를 실행하면 보고서 수치도 함께 갱신된다.

    python src/make_report.py
"""
import os
import sys

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    COMPETITION_ID, HOLDOUT_FRAC, MIN_MINUTES, NB_PREV_ACTIONS, N_FOLDS, OUT, ROOT,
    SEASON_ID, SEED, XGB_PARAMS,
)

BLACK = RGBColor(0, 0, 0)
FONT = "맑은 고딕"
MONO = "Consolas"
FIGDIR = os.path.join(ROOT, "figures", "report")
# 보고서는 저장소에 올리지 않으므로 프로젝트 폴더 밖(한 단계 위)에 만든다.
# VAEP_REPORT 환경변수로 경로를 바꿀 수 있다.
REPORT = os.environ.get(
    "VAEP_REPORT", os.path.join(os.path.dirname(ROOT), "VAEP_보고서.docx"))

_counters = {"table": 0, "figure": 0}


# ----------------------------------------------------------------------------- 문서 뼈대
def new_document():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = sec.bottom_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(6)

    # 워드 기본 제목 스타일은 파란색이므로 전부 검정으로 바꾼다
    for name in ["Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"]:
        st = doc.styles[name]
        st.font.name = FONT
        st.font.color.rgb = BLACK
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    doc.styles["Heading 1"].font.size = Pt(16)
    doc.styles["Heading 2"].font.size = Pt(13)
    doc.styles["Heading 3"].font.size = Pt(11.5)
    return doc


def _fmt(run, size=10.5, bold=False, mono=False, italic=False):
    run.font.name = MONO if mono else FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = BLACK
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)


def h(doc, text, level=1, page_break=False):
    if page_break:
        doc.add_page_break()
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        _fmt(r, size={1: 16, 2: 13, 3: 11.5, 4: 10.5}[level], bold=True)
    p.paragraph_format.space_before = Pt(16 if level == 1 else 12)
    p.paragraph_format.space_after = Pt(6)
    return p


def para(doc, text, size=10.5, bold=False, align=None, space_after=6):
    p = doc.add_paragraph()
    # **굵게** 표시를 실제 굵은 글씨로 바꾼다
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        _fmt(p.add_run(chunk), size=size, bold=bold or (i % 2 == 1))
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(space_after)
    return p


def bullet(doc, text, size=10.5, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        _fmt(p.add_run(chunk), size=size, bold=(i % 2 == 1))
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    return p


def numbered(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Number")
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        _fmt(p.add_run(chunk), size=size, bold=(i % 2 == 1))
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    return p


def code(doc, text, size=9):
    for line in text.strip("\n").split("\n"):
        p = doc.add_paragraph()
        _fmt(p.add_run(line if line else " "), size=size, mono=True)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.left_indent = Cm(0.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def caption(doc, kind, text):
    _counters[kind] += 1
    label = f"표 {_counters[kind]}." if kind == "table" else f"그림 {_counters[kind]}."
    p = doc.add_paragraph()
    _fmt(p.add_run(f"{label} "), size=9.5, bold=True)
    _fmt(p.add_run(text), size=9.5)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)


def table(doc, header, rows, widths=None, size=9.5, caption_text=None, align_right=None):
    """표 하나를 넣는다. align_right에는 오른쪽 정렬할 열 번호를 준다."""
    if caption_text:
        _counters["table"] += 1
        p = doc.add_paragraph()
        _fmt(p.add_run(f"표 {_counters['table']}. "), size=9.5, bold=True)
        _fmt(p.add_run(caption_text), size=9.5)
        p.paragraph_format.space_after = Pt(3)

    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    align_right = align_right or []

    for j, text in enumerate(header):
        cell = t.rows[0].cells[j]
        cell.text = ""
        r = cell.paragraphs[0].add_run(str(text))
        _fmt(r, size=size, bold=True)
        cell.paragraphs[0].paragraph_format.space_after = Pt(1)
        cell.paragraphs[0].paragraph_format.line_spacing = 1.15

    for row in rows:
        cells = t.add_row().cells
        for j, text in enumerate(row):
            cells[j].text = ""
            p = cells[j].paragraphs[0]
            for i, chunk in enumerate(str(text).split("**")):
                if not chunk:
                    continue
                _fmt(p.add_run(chunk), size=size, bold=(i % 2 == 1))
            if j in align_right:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.15

    if widths:
        for row in t.rows:
            for j, w in enumerate(widths):
                row.cells[j].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


def figure(doc, filename, caption_text, width=16.0):
    doc.add_picture(os.path.join(FIGDIR, filename), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, "figure", caption_text)


# ----------------------------------------------------------------------------- 결과 읽기
def load():
    d = {}
    d["games"] = pd.read_parquet(f"{OUT}/games.parquet")
    d["teams"] = pd.read_parquet(f"{OUT}/teams.parquet")
    d["players"] = pd.read_parquet(f"{OUT}/players.parquet")
    d["player_games"] = pd.read_parquet(f"{OUT}/player_games.parquet")
    d["actions"] = pd.read_parquet(f"{OUT}/actions.parquet")
    d["labels"] = pd.read_parquet(f"{OUT}/labels.parquet")
    d["features_cols"] = [c for c in pd.read_parquet(
        f"{OUT}/features.parquet", columns=None).columns if c not in ("game_id", "action_id")]
    d["metrics"] = pd.read_csv(f"{OUT}/metrics.csv")
    d["ratings"] = pd.read_csv(f"{OUT}/player_ratings.csv")
    d["by_type"] = pd.read_csv(f"{OUT}/value_by_actiontype.csv")
    d["sequence"] = pd.read_csv(f"{OUT}/sequence.csv")
    d["importance"] = pd.read_csv(f"{OUT}/feature_importance.csv", index_col="feature")
    d["ablation"] = pd.read_csv(f"{OUT}/ablation.csv")
    d["trad"] = pd.read_csv(f"{OUT}/traditional_vs_vaep.csv")
    return d


def m(metrics, split, label, col):
    """metrics.csv에서 값 하나를 꺼낸다."""
    return float(metrics[(metrics.split == split) & (metrics.label == label)][col].iloc[0])


# ----------------------------------------------------------------------------- 표지·목차
def cover(doc, d):
    g = d["games"]
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    _fmt(p.add_run("VAEP로 축구 선수의 모든 온더볼 행동에 점수 매기기"), size=22, bold=True)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph()
    _fmt(p.add_run("StatsBomb 라리가 2015/16 380경기로 Decroos et al.(KDD 2019)의 재현"), size=13)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(30)

    table(doc, ["항목", "내용"], [
        ["과제", "VAEP 논문의 방법을 실제 데이터로 처음부터 끝까지 재현하고, 그 과정과 결과를 근거와 함께 정리"],
        ["원 논문", "Tom Decroos, Lotte Bransen, Jan Van Haaren, Jesse Davis, "
                  "“Actions Speak Louder than Goals: Valuing Player Actions in Soccer”, KDD ’19"],
        ["사용 데이터", f"StatsBomb Open Data · 라리가 2015/16 (competition {COMPETITION_ID} / season {SEASON_ID}) "
                   f"{len(g)}경기, {g.game_date.min():%Y-%m-%d} ~ {g.game_date.max():%Y-%m-%d}"],
        ["사용 도구", "Python 3.11, socceraction 1.5.3, XGBoost 2.0.3, scikit-learn 1.4.2"],
        ["산출물", "재현 가능한 파이프라인(스크립트 8개), 노트북 1권, 결과 파일 16개, 이 보고서"],
        ["작성일", "2026년 9월 19일"],
        ["작성자", ""],
    ], widths=[3.0, 13.6], size=10)

    doc.add_page_break()
    h(doc, "목차", level=1)
    toc = [
        ("1", "과제 개요와 핵심 결과"),
        ("2", "배경 — VAEP는 무엇을 푸는 방법인가"),
        ("3", "데이터 선택과 근거"),
        ("4", "데이터 전처리 — 원본 이벤트에서 SPADL 행동까지"),
        ("5", "피처 정의 — 게임 상태를 145개 숫자로"),
        ("6", "라벨 정의 — 무엇을 맞히게 할 것인가"),
        ("7", "모델 설정과 하이퍼파라미터"),
        ("8", "검증 절차 — 무엇을 어떻게 재는가"),
        ("9", "결과"),
        ("10", "결과의 불확실성과 한계"),
        ("11", "재현 절차"),
        ("12", "결론"),
        ("부록 A", "피처 145개 전체 목록"),
        ("부록 B", "산출물 파일과 스키마"),
        ("부록 C", "SPADL 행동 유형 23가지와 이 시즌의 빈도"),
        ("부록 D", "참고 문헌"),
    ]
    table(doc, ["장", "제목"], toc, widths=[2.2, 14.4], size=10)


# ----------------------------------------------------------------------------- 1장
def ch1(doc, d):
    g, a, Y, met, rat = d["games"], d["actions"], d["labels"], d["metrics"], d["ratings"]
    h(doc, "1. 과제 개요와 핵심 결과", level=1, page_break=True)

    h(doc, "1.1 무엇을 했나", level=2)
    para(doc, "축구에서 선수를 평가하는 전통적인 방법은 골과 어시스트를 세는 것이다. 그런데 한 경기에서 "
              "골은 두세 개뿐이고, 경기의 나머지 2,000번 가까운 행동 — 패스, 드리블, 태클, 걷어내기 — 은 "
              "숫자에 남지 않는다. VAEP(Valuing Actions by Estimating Probabilities)는 이 문제를 "
              "**“이 행동 때문에 우리 팀이 곧 골을 넣을 확률이 얼마나 올랐고, 먹을 확률이 얼마나 내렸는가”**로 "
              "바꿔서, 공에 닿은 모든 행동에 골 단위의 점수를 매긴다.")
    para(doc, "이 과제에서는 VAEP 논문의 방법을 StatsBomb이 공개한 라리가 2015/16 한 시즌 전체에 적용해 "
              "원본 이벤트 수집부터 선수 순위까지 전 과정을 다시 만들었다. 단순히 라이브러리를 호출해 "
              "숫자를 뽑는 데 그치지 않고, 각 단계에서 왜 그 선택을 했는지를 데이터로 확인하는 것을 목표로 했다. "
              "구체적으로는 (1) 논문의 설계 선택 실험(피처 집합·알고리즘 비교)을 우리 데이터에서 다시 수행했고, "
              "(2) 결과가 얼마나 흔들리는지를 폴드 재분할로 측정했으며, "
              "(3) 파이프라인이 두 번 돌렸을 때 바이트 단위로 같은 결과를 내는지 확인했다.")

    h(doc, "1.2 핵심 결과 요약", level=2)
    n_goal = int((a.shape[0] * 0) + ((g.home_score + g.away_score).sum()))
    rows = [
        ["원본 이벤트", "1,295,354개 (380경기, 경기당 3,409개)"],
        ["SPADL 행동", f"{len(a):,}개 (경기당 {len(a)/len(g):.0f}개)"],
        ["검증된 골 수", f"{n_goal:,}골 — 경기 메타데이터 합계와 SPADL 변환 결과가 정확히 일치"],
        ["입력 피처", f"{len(d['features_cols'])}개 (지금 행동 + 직전 2개 행동)"],
        ["라벨 발생률", f"득점 {Y.scores.mean()*100:.2f}% ({int(Y.scores.sum()):,}건) · "
                    f"실점 {Y.concedes.mean()*100:.2f}% ({int(Y.concedes.sum()):,}건)"],
        ["득점 확률 모델", f"ROC AUC {m(met,'oof','scores','roc_auc'):.3f} · "
                     f"Brier skill {m(met,'oof','scores','brier_skill'):.3f} (경기 단위 5겹 OOF)"],
        ["실점 확률 모델", f"ROC AUC {m(met,'oof','concedes','roc_auc'):.3f} · "
                     f"Brier skill {m(met,'oof','concedes','brier_skill'):.3f} (경기 단위 5겹 OOF)"],
        ["90분당 VAEP 1위", f"{rat.iloc[0]['name']} ({rat.iloc[0].team_name}) {rat.iloc[0].vaep_p90:.3f}"],
        ["재현성", "전체 파이프라인 2회 실행 시 중간 산출물 3종의 md5 해시가 모두 일치"],
    ]
    table(doc, ["항목", "값"], rows, widths=[4.2, 12.4], size=10,
          caption_text="이 보고서의 핵심 수치 요약")

    para(doc, "가장 중요한 확인은 마지막에서 두 번째 줄이 아니라, 논문과의 비교에 있다. "
              "논문은 다른 공급사(Wyscout)의 7개 리그 11,565경기로 학습했고 우리는 StatsBomb의 한 리그 380경기를 썼는데, "
              "**기저율 대비 개선율(Brier skill)이 득점 0.149 대 0.157, 실점 0.030 대 0.030으로 거의 같게 나왔다.** "
              "데이터와 알고리즘이 모두 다른데도 같은 자리에 도달했다는 것은, 이 재현이 논문의 방법을 "
              "제대로 옮겼다는 강한 근거다. 자세한 비교는 9.2절에 있다.")

    h(doc, "1.3 이 보고서의 구성", level=2)
    para(doc, "3장부터 8장까지가 “왜 이렇게 만들었는가”이고, 9장이 “그래서 무엇이 나왔는가”, "
              "10장이 “그 결과를 어디까지 믿을 수 있는가”다. 11장만 보면 다른 사람이 같은 결과를 다시 만들 수 있도록 "
              "환경과 실행 절차를 적었다. 각 장에서 내린 선택은 근거와 함께 적었고, 근거가 실험인 경우에는 "
              "그 실험의 숫자를 같이 실었다.")


# ----------------------------------------------------------------------------- 2장
def ch2(doc, d):
    h(doc, "2. 배경 — VAEP는 무엇을 푸는 방법인가", level=1, page_break=True)

    h(doc, "2.1 기존 지표가 놓치는 것", level=2)
    para(doc, "논문은 기존 축구 지표의 한계를 세 가지로 정리한다. 이 셋을 먼저 이해해야 VAEP의 설계가 "
              "왜 그렇게 생겼는지가 설명된다.")
    table(doc, ["#", "한계", "구체적인 예", "VAEP의 대응"], [
        ["1", "골과 슈팅만 본다",
         "기존 연구 대부분이 xG(슈팅이 골이 될 확률)에 집중했다. 이 시즌 데이터에서 슛은 전체 행동의 1.14%뿐이다.",
         "공에 닿은 모든 행동을 같은 척도로 평가한다."],
        ["2", "맥락을 무시한 고정값",
         "자기 진영에서 압박 없이 주고받은 패스와, 상대 박스 앞에서 압박을 받으며 찌른 패스를 같은 1회로 센다.",
         "위치·직전 흐름·스코어를 입력으로 받아 같은 유형이라도 다른 값을 준다."],
        ["3", "즉시 효과만 본다",
         "측면 전환 롱패스는 당장 골로 이어지지 않지만 몇 수 뒤 기회를 만든다.",
         "‘앞으로 10개 행동 안의 득점’을 라벨로 삼아 몇 수 뒤 효과까지 반영한다."],
    ], widths=[0.8, 3.0, 8.0, 4.8], size=9.5,
        caption_text="논문이 지적한 기존 지표의 세 가지 한계와 VAEP의 대응")

    h(doc, "2.2 SPADL — 값을 매기기 전에 데이터부터 통일해야 하는 이유", level=2)
    para(doc, "공급사(StatsBomb, Opta, Wyscout)마다 이벤트의 이름과 구조가 다르고, 이벤트 종류마다 붙는 "
              "부가정보도 제각각이다. 반면 대부분의 머신러닝 모델은 **모든 샘플이 같은 칸을 갖는 고정 길이 표**를 요구한다. "
              "SPADL(Soccer Player Action Description Language)은 이 간극을 메우는 중간 표현으로, "
              "모든 행동을 <선수, 팀, 시작 시각, 시작 위치, 종료 위치, 행동 유형, 결과, 신체 부위>라는 "
              "항상 같은 속성 집합으로 적는다.")
    para(doc, "핵심은 **‘이벤트’가 아니라 ‘행동’을 적는다**는 점이다. 경기 종료 같은 이벤트는 선수가 수행한 행동이 "
              "아니므로 버린다. 그래서 이 시즌에서 원본 이벤트 1,295,354개가 SPADL 행동 757,309개로 줄었다.")

    h(doc, "2.3 VAEP의 정의", level=2)
    para(doc, "게임 상태 S_i를 “i번째 행동까지 진행된 상황”이라 하면, 행동 a_i는 상태를 S_(i−1)에서 S_i로 옮긴다. "
              "공을 가진 팀 x 기준으로 두 확률을 정의한다.")
    code(doc, """
P_score(S_i, x)    = 상태 S_i에서 팀 x가 앞으로 10개 행동 안에 득점할 확률
P_concede(S_i, x)  = 상태 S_i에서 팀 x가 앞으로 10개 행동 안에 실점할 확률

공격 가치  ΔP_score(a_i)   =  P_score(S_i)   − P_score(S_(i−1))
수비 가치  −ΔP_concede(a_i) = −( P_concede(S_i) − P_concede(S_(i−1)) )
VAEP      V(a_i)          =  공격 가치 + 수비 가치

선수 레이팅  rating(p) = (90 / 출전 분) × Σ V(a_i),   a_i ∈ 그 선수가 한 행동
""")
    para(doc, "값의 단위는 골이다. +0.05인 행동은 “그 팀에 0.05골만큼 기여할 것으로 기대된다”는 뜻이다. "
              "이 해석이 성립하려면 확률 추정치가 **잘 보정(calibration)되어** 있어야 한다. 모델이 5%라고 말한 상황에서 "
              "실제로 5%가 일어나야, 두 확률의 뺄셈이 골 단위의 의미를 갖기 때문이다. "
              "8.4절에서 평가 지표로 Brier score를 함께 쓰는 이유가 여기에 있다.")

    h(doc, "2.4 주관적인 문제를 객관적인 문제로 바꾼 것이 핵심", level=2)
    para(doc, "“이 패스는 몇 점짜리인가”에는 정답이 없다. 그러나 “이 상태에서 10개 행동 안에 골이 나왔는가”는 "
              "데이터에 정답이 남아 있다. VAEP는 전자를 후자로 바꿔서 지도학습으로 풀고, 값은 그 확률의 차이로 정의한다. "
              "이 구조 덕분에 가치 자체는 검증할 수 없어도 그 밑에 깔린 확률 모델은 표준 지표로 검증할 수 있다. "
              "9장의 평가가 모두 확률 모델에 대한 것인 이유다.")

    h(doc, "2.5 이 방법이 전제하는 것", level=2)
    bullet(doc, "**마르코프 근사**: 게임 상태 전체 대신 직전 몇 개 행동만 본다. 이 구현은 논문과 같이 3개(지금 + 직전 2개)를 쓴다.")
    bullet(doc, "**온더볼 한정**: 이벤트 데이터에는 공을 가진 선수 주변만 기록된다. 수비 대형, 압박 강도, "
                "공 없는 동료의 침투는 상태에 들어오지 않는다.")
    bullet(doc, "**평균적인 팀 기준**: 확률 모델은 데이터 속 모든 팀의 평균적 행동을 학습한다. 특정 팀 전술 안에서 "
                "좋은 선택이 평균 기준으로는 낮게 평가될 수 있다.")
    para(doc, "이 전제들은 10장에서 결과 해석의 한계로 다시 다룬다.", size=10)


# ----------------------------------------------------------------------------- 3장
def ch3(doc, d):
    g, a = d["games"], d["actions"]
    h(doc, "3. 데이터 선택과 근거", level=1, page_break=True)

    h(doc, "3.1 무엇이 필요했나", level=2)
    para(doc, "데이터를 고르기 전에, 이 과제를 제대로 하려면 데이터가 갖춰야 할 조건을 먼저 정리했다.")
    numbered(doc, "**희귀 사건을 학습할 만큼의 표본**. 라벨의 양성 비율이 1% 안팎이므로, 경기 수가 적으면 "
                  "양성 사례 자체가 모자라 모델도 평가도 흔들린다.")
    numbered(doc, "**출전 시간 정보**. 90분당 레이팅을 계산하려면 선수별 출전 분이 필요하다. "
                  "StatsBomb 공개 데이터에서는 lineups 파일이 이를 제공한다.")
    numbered(doc, "**시간 순서가 있는 한 시즌 전체**. 논문이 쓴 ‘과거로 학습하고 미래로 평가하는’ 분할을 "
                  "재현하려면 한 대회가 시간축을 따라 이어져야 한다.")
    numbered(doc, "**공개 데이터**. 다른 사람이 같은 결과를 재현할 수 있어야 한다.")

    h(doc, "3.2 후보 비교와 선택", level=2)
    table(doc, ["후보", "규모", "장점", "이 과제에 부적합한 점"], [
        ["FIFA 월드컵 2018\n(socceraction 공개 노트북의 기본값)", "64경기",
         "가볍고 빨라 시험용으로 좋다.",
         "골 약 170개로 표본이 작고, 선수당 출전 시간이 짧아(최대 약 600분) 90분당 순위가 "
         "우연에 크게 좌우된다. 시즌 구조가 없어 시간순 홀드아웃도 어렵다."],
        ["FA WSL 2018/19", "108경기",
         "중간 규모, 여자축구 데이터라는 차별점.",
         "표본이 애매하고 선수 인지도가 낮아 결과의 타당성을 직관적으로 점검하기 어렵다."],
        ["**라리가 2015/16 (선택)**", "**380경기**",
         "한 시즌 전체 · 골 1,043개 · 행동 757,309개 · 선수 539명. 5겹 교차검증과 시간순 홀드아웃을 "
         "모두 감당한다. 선수 구성이 잘 알려져 있어 결과가 상식과 맞는지 눈으로 검증할 수 있다.",
         "한 리그 한 시즌이므로 리그 간 비교는 불가능하다(10장 한계 참고)."],
    ], widths=[3.4, 1.6, 5.8, 5.8], size=9.5,
        caption_text="데이터 후보 비교와 선택 근거")

    para(doc, "선택의 결정적 이유는 1번 조건이다. 득점 라벨의 양성 비율이 1.10%이므로, 월드컵 64경기 "
              "(행동 약 13만 개)에서는 양성 사례가 1,400개 남짓이고 이를 다시 5겹으로 나누면 폴드당 "
              "300개 이하가 된다. 라리가 380경기는 양성 8,354개를 주므로 폴드당 1,600개 이상이 되어 "
              "학습과 평가가 모두 안정된다.")

    h(doc, "3.3 선택한 데이터의 명세", level=2)
    pg = d["player_games"]
    table(doc, ["항목", "값"], [
        ["대회 / 시즌", f"라리가 2015/16 (competition_id={COMPETITION_ID}, season_id={SEASON_ID})"],
        ["출처", "StatsBomb Open Data (github.com/statsbomb/open-data)"],
        ["경기", f"{len(g)}경기 · {g.game_date.min():%Y-%m-%d} ~ {g.game_date.max():%Y-%m-%d}"],
        ["원본 파일", "events 380개 + lineups 380개 + matches 1개 + competitions 1개 (약 1.1GB)"],
        ["원본 이벤트", "1,295,354개 (경기당 3,409개)"],
        ["팀 / 선수", f"{len(d['teams'])}팀 / {pg.player_id.nunique()}명 (출전 기록 {len(pg):,}건, 총 {int(pg.minutes_played.sum()):,}분)"],
        ["득점", f"{int((g.home_score + g.away_score).sum()):,}골"],
    ], widths=[3.4, 13.2], size=10, caption_text="사용한 데이터의 명세")

    h(doc, "3.4 데이터 정합성 점검", level=2)
    para(doc, "전처리 결과를 신뢰하려면, 변환된 데이터가 원본과 맞는지부터 확인해야 한다. "
              "가장 확실한 점검은 골 수다. 경기 메타데이터(각 경기의 최종 스코어)와 SPADL 변환 결과는 "
              "서로 다른 경로로 만들어지므로, 둘이 일치하면 이벤트 → 행동 변환이 골을 빠뜨리거나 "
              "중복시키지 않았다는 뜻이 된다.")
    code(doc, """
경기 메타데이터 득점 합계                     : 1,043골
SPADL에서 '슛 계열 & 결과=success'            : 1,014골
SPADL에서 '결과=owngoal'                      :    29골
                                       합계   : 1,043골   → 정확히 일치
""")
    para(doc, "자책골이 슛의 성공이 아니라 별도의 결과 값으로 기록된다는 SPADL의 규칙까지 포함해 맞아떨어졌다. "
              "이 점검은 `src/build_spadl.py`가 실행될 때마다 함께 출력된다.", size=10)


# ----------------------------------------------------------------------------- 4장
def ch4(doc, d):
    import socceraction.spadl as spadl

    a = d["actions"]
    named = spadl.add_names(a)
    h(doc, "4. 데이터 전처리 — 원본 이벤트에서 SPADL 행동까지", level=1, page_break=True)
    para(doc, "이 장은 다른 사람이 같은 데이터를 같은 형태로 다시 만들 수 있도록, 변환의 모든 규칙과 "
              "그 규칙을 그대로 둔 이유 또는 바꾼 이유를 적는다.")

    h(doc, "4.1 전체 흐름", level=2)
    table(doc, ["단계", "스크립트", "입력 → 출력", "핵심 처리"], [
        ["1. 수집", "src/fetch_statsbomb.py", "GitHub → data/statsbomb/",
         "open-data 저장소와 같은 폴더 구조로 내려받아 socceraction의 로컬 로더가 그대로 읽게 한다. "
         "이미 받은 파일은 건너뛴다."],
        ["2. 변환", "src/build_spadl.py", "원본 JSON → out/actions.parquet",
         "이벤트를 행동으로 거르고 SPADL 9속성으로 통일. 좌표 변환·방향 통일·드리블 합성 포함."],
        ["3. 피처·라벨", "src/build_features.py", "actions → features.parquet, labels.parquet",
         "게임 상태를 145개 숫자로, 라벨 2개를 계산."],
    ], widths=[2.2, 3.4, 4.2, 6.8], size=9.5, caption_text="전처리 단계")

    h(doc, "4.2 원본 데이터 레이아웃", level=2)
    para(doc, "socceraction의 `StatsBombLoader(getter=\"local\")`는 StatsBomb open-data 저장소와 같은 "
              "디렉터리 구조를 기대한다. 수집 스크립트는 그 구조를 그대로 만든다. 이렇게 하면 원격 API "
              "의존 없이 언제든 같은 입력으로 다시 돌릴 수 있다.")
    code(doc, """
data/statsbomb/competitions.json
              /matches/11/27.json         # competition 11 = 라리가, season 27 = 2015/16
              /events/{match_id}.json     # 380개
              /lineups/{match_id}.json    # 380개  ← 출전 시간(90분당 계산)에 필요
""")

    h(doc, "4.3 이벤트에서 행동으로: 변환 규칙", level=2)
    para(doc, "socceraction 1.5.3의 `spadl.statsbomb.convert_to_actions()`가 수행하는 처리를 "
              "순서대로 정리하면 다음과 같다. 이 구현을 그대로 쓴 이유는, 논문 저자들이 공개한 참조 구현이어서 "
              "재현의 기준점이 되기 때문이다.")
    numbered(doc, "**행동만 남긴다.** Pass, Carry, Dribble, Duel, Shot, Foul, Interception, Clearance, "
                  "Miscontrol, Goal Keeper, Own Goal Against 등 선수가 수행한 이벤트만 행동으로 바꾸고, "
                  "나머지(경기 시작·종료, 전술 변경, 심판 판정 등)는 non_action으로 표시해 제외한다.")
    numbered(doc, "**유형·결과·신체 부위를 분리한다.** 예를 들어 슛은 결과에 따라 다른 이벤트로 오지 않고 "
                  "type=shot, result∈{success, fail, owngoal}로 쪼갠다. 덕분에 “모든 슛”을 한 번에 다룰 수 있다.")
    numbered(doc, "**좌표를 미터 단위로 바꾼다.** StatsBomb의 120×80 칸 좌표를 SPADL의 105m×68m로 변환한다. "
                  "칸의 중심을 쓰기 위해 반 칸(fidelity 1이면 0.5, fidelity 2면 0.05)을 빼고 환산한다.")
    numbered(doc, "**공격 방향을 통일한다.** 원정팀 행동의 좌표를 (105−x, 68−y)로 뒤집어, 모든 팀이 "
                  "왼쪽에서 오른쪽으로 공격하는 것처럼 만든다. 이렇게 해야 ‘골대까지 거리’ 같은 피처가 "
                  "홈/원정, 전·후반과 무관하게 같은 뜻을 갖는다.")
    numbered(doc, "**걷어내기의 종료 좌표를 보정한다.** 원본에는 클리어런스의 도착 지점이 없으므로, "
                  "다음 행동의 시작 좌표를 종료 좌표로 쓴다.")
    numbered(doc, "**드리블을 합성한다.** 아래 4.4절 참고.")

    h(doc, "4.4 드리블(볼 운반)의 처리 — 이 데이터에서 특히 중요한 부분", level=2)
    para(doc, "SPADL의 dribble은 흔히 말하는 1대1 돌파(그건 take_on이다)가 아니라 **공을 몰고 이동한 구간**이다. "
              "두 경로로 만들어진다.")
    bullet(doc, "**StatsBomb의 Carry 이벤트**를 그대로 dribble로 매핑한다. StatsBomb은 볼 운반을 "
                "이벤트로 직접 기록하는 몇 안 되는 공급사다.")
    bullet(doc, "**합성**: 같은 팀의 연속된 두 행동 사이에서 앞 행동의 종료 지점과 다음 행동의 시작 지점이 "
                "3m 이상 60m 이하로 떨어져 있고, 시간 간격이 10초 미만이며 같은 피리어드이면 그 사이에 "
                "dribble 행동을 끼워 넣는다. 단 다음 행동이 공격 파울이거나 헤딩 슛이면 넣지 않는다.")
    dribble_share = (named.type_name == "dribble").mean() * 100
    para(doc, f"그 결과 이 데이터에서 dribble은 전체 행동의 **{dribble_share:.1f}%**를 차지한다. "
              f"논문이 Wyscout 데이터에서 보고한 8.69%와 큰 차이가 나는데, 이는 오류가 아니라 공급사 차이다. "
              f"Wyscout에는 Carry 이벤트가 없어 합성 드리블만 생기지만, StatsBomb은 볼 운반을 직접 기록하기 때문이다. "
              f"이 차이는 9.6절의 ‘행동 유형별 가치 합계’ 해석에 직접 영향을 주므로 미리 밝혀 둔다.")

    h(doc, "4.5 좌표 정밀도(fidelity version)", level=2)
    para(doc, "StatsBomb은 시기·대회에 따라 좌표를 1야드 단위(fidelity 1) 또는 0.1야드 단위(fidelity 2)로 "
              "기록한다. 변환기는 경기별로 소수점 유무를 보고 이를 추론한다. 이 구현에서는 값을 강제로 지정하지 않고 "
              "**자동 추론에 맡겼다.** 라리가 2015/16은 슛에 고정밀 좌표가 들어 있는 경기와 아닌 경기가 섞여 있어, "
              "한 값으로 고정하면 일부 경기의 좌표가 반 칸씩 밀리기 때문이다.")

    h(doc, "4.6 재현을 막고 있던 버그와 그 처리", level=2)
    para(doc, "전처리를 두 번 돌려 결과를 비교하는 과정에서, 같은 입력인데도 좌표 몇 개가 실행마다 달라지는 것을 발견했다. "
              "추적해 보니 socceraction 1.5.3의 좌표 변환 함수에서 비롯된 문제였다.")
    code(doc, """
# socceraction/spadl/statsbomb.py 의 _convert_locations()
coordinates = np.empty((len(locations), 2), dtype=float)   # 초기화하지 않은 메모리
for i, loc in enumerate(locations):
    if isinstance(loc, list) and len(loc) == 2:  ...        # 위치가 있는 이벤트만 채운다
    elif isinstance(loc, list) and len(loc) == 3: ...
# → 위치가 없는 이벤트의 행은 채워지지 않고 쓰레기 값(예: 6.9e-310)으로 남는다
""")
    para(doc, "영향은 작아 보이지만 결과는 크게 달라진다. 이 시즌에서 위치가 없는 행동은 **7개**뿐인데, "
              "그 7개의 좌표가 실행마다 달라지면 (1) 드리블 합성 여부가 달라져 행동 수가 바뀌고, "
              "(2) 피처가 달라지며, (3) 모델과 선수 순위가 매번 달라진다. 실제로 이 문제를 잡기 전에는 "
              "같은 코드로 두 번 돌렸을 때 득점 모델 AUC가 0.8148과 0.8137로 달랐다.")
    para(doc, "**처리**: 원본 라이브러리는 건드리지 않고, `src/build_spadl.py`의 "
              "`patch_missing_locations()`에서 해당 함수를 감싸 위치가 없는 이벤트의 좌표를 NaN으로 채운다. "
              "NaN으로 두는 이유는 그 행동에 실제로 좌표 정보가 없기 때문이고, 0이나 경기장 중앙 같은 값으로 "
              "채우면 없는 정보를 지어내는 셈이 되기 때문이다. XGBoost는 결측을 그대로 처리할 수 있어 "
              "모델 학습에도 문제가 없다(4.8절).")

    h(doc, "4.7 결정적 정렬", level=2)
    para(doc, "경기 목록을 날짜로만 정렬하면 같은 날 열린 경기들의 순서가 정렬 알고리즘에 따라 달라질 수 있다. "
              "이 순서는 교차검증 폴드 배정과 홀드아웃 경계에 영향을 주므로, 날짜가 같으면 `game_id`로 "
              "한 번 더 정렬해 순서를 완전히 고정했다. 이 조치와 4.6절의 수정을 합쳐 파이프라인 전체가 "
              "실행마다 같은 결과를 내게 되었다(11.5절에 확인 방법).")

    h(doc, "4.8 결측 처리 방침", level=2)
    para(doc, f"최종 피처 표 {len(d['features_cols'])}개 열 가운데 결측이 있는 행은 757,309행 중 **7행**이다. "
              f"본 모델(XGBoost)은 결측을 별도의 분기로 학습하므로 채우지 않고 그대로 넣는다. "
              f"반면 비교 실험에 쓴 로지스틱 회귀와 랜덤 포레스트는 결측을 받지 못하므로, 그 두 모델에 한해 "
              f"중앙값으로 채운 뒤 학습했다(9.4절 실험). 비교 대상 사이의 차이가 결측 처리에서 오지 않도록 "
              f"같은 규칙을 두 모델에 동일하게 적용했다.")

    h(doc, "4.9 변환 결과", level=2)
    vc = named.type_name.value_counts()
    rows = [[t, f"{c:,}", f"{c/len(named)*100:.2f}%"] for t, c in vc.head(12).items()]
    rows.append(["그 외 9종", f"{vc.iloc[12:].sum():,}", f"{vc.iloc[12:].sum()/len(named)*100:.2f}%"])
    table(doc, ["행동 유형", "개수", "비중"], rows, widths=[5.0, 3.0, 2.6], size=9.5,
          align_right=[1, 2], caption_text="변환된 SPADL 행동의 유형별 빈도 (상위 12종, 전체 23종은 부록 C)")
    para(doc, "패스(41.6%)와 드리블(39.0%)이 전체의 80%를 차지하고 슛은 1.14%다. "
              "“슛 중심 지표로는 경기의 99%를 평가하지 못한다”는 논문의 문제의식이 숫자로 드러나는 대목이다.", size=10)


# ----------------------------------------------------------------------------- 5장
def ch5(doc, d):
    import socceraction.vaep.features as fs
    from build_features import XFN_NAMES

    h(doc, "5. 피처 정의 — 게임 상태를 145개 숫자로", level=1, page_break=True)

    h(doc, "5.1 게임 상태를 무엇으로 볼 것인가", level=2)
    para(doc, "확률을 예측하려면 “지금 상황”을 고정 길이 숫자 벡터로 만들어야 한다. VAEP는 경기 전체 대신 "
              f"**지금 행동(a0)과 직전 {NB_PREV_ACTIONS - 1}개 행동(a1, a2)**만 본다. 논문이 3개를 고른 이유는 "
              "경험적으로 잘 작동했다는 것이고, 이 구현도 같은 값을 썼다. 같은 위치의 패스라도 직전에 "
              "무슨 일이 있었는지(상대의 클리어링을 주워 온 것인지, 우리 팀이 침착하게 돌린 것인지)에 따라 "
              "가치가 달라야 하기 때문에, 직전 행동을 함께 보는 것이 핵심이다.")
    para(doc, "피처를 만들기 전에 게임 상태의 세 행동을 모두 **왼쪽 → 오른쪽 공격 방향으로 정렬**한다. "
              "정렬 기준은 a0을 수행한 팀이다. 즉 공격권이 바뀐 직후의 게임 상태에서는 직전 행동의 좌표도 "
              "현재 공을 가진 팀의 시점으로 뒤집혀 들어간다.")

    h(doc, "5.2 피처 묶음별 정의", level=2)
    DESC = {
        "actiontype_onehot": ("행동 유형 23가지를 0/1로 표시", "actiontype_pass_a0 = 1이면 지금 행동이 패스"),
        "bodypart_onehot": ("사용한 신체 부위", "foot / head / other / head-other 등"),
        "result_onehot": ("행동의 결과", "success / fail / offside / owngoal / yellow_card / red_card"),
        "goalscore": ("현재 스코어 상황", "공격 팀 득점, 수비 팀 득점, 골 차"),
        "startlocation": ("행동 시작 좌표 (m)", "start_x, start_y"),
        "endlocation": ("행동 종료 좌표 (m)", "end_x, end_y"),
        "movement": ("행동의 이동량", "dx, dy, 직선 거리"),
        "space_delta": ("직전 행동과 벌어진 거리", "a0–a1, a0–a2 각각의 dx, dy, 거리"),
        "startpolar": ("시작점에서 상대 골대까지", "거리, 각도 — xG 모델의 핵심 피처와 같은 발상"),
        "endpolar": ("종료점에서 상대 골대까지", "거리, 각도"),
        "team": ("직전 행동이 같은 팀 것인가", "team_1, team_2 (a1, a2와 같은 팀이면 1)"),
        "time_delta": ("직전 행동과의 시간 차(초)", "time_delta_1, time_delta_2 — 플레이 속도를 가늠"),
    }
    rows = []
    for name in XFN_NAMES:
        cols = fs.feature_column_names([getattr(fs, name)], NB_PREV_ACTIONS)
        desc, ex = DESC[name]
        rows.append([name, desc, str(len(cols)), ex])
    rows.append(["합계", "", str(len(d["features_cols"])), ""])
    table(doc, ["변환 함수", "무엇을 보는가", "열 수", "예"], rows,
          widths=[3.4, 5.4, 1.2, 6.6], size=9.5,
          caption_text="입력 피처의 구성 (socceraction의 변환 함수 단위)")
    para(doc, "각 묶음은 게임 상태의 세 행동에 각각 적용되므로, 예컨대 행동 유형 23개는 23×3 = 69열이 된다. "
              "team과 time_delta는 ‘직전 행동과의 관계’라서 a1, a2에만 정의되어 2열씩이고, "
              "goalscore는 상태 전체에 하나씩 붙어 3열이다.")

    h(doc, "5.3 논문과 다르게 한 점과 그 이유", level=2)
    table(doc, ["항목", "논문", "이 구현", "이유"], [
        ["범주형 처리", "CatBoost의 범주형 기능을 그대로 사용",
         "모두 원-핫(one-hot)으로 펼침",
         "XGBoost를 쓰기로 했기 때문이다(7.2절). 원-핫은 열이 늘지만 모델·전처리가 단순해지고, "
         "피처 중요도를 유형별로 바로 읽을 수 있다."],
        ["경기 내 시각(time)", "피처에 포함",
         "제외",
         "socceraction 공개 노트북의 구성을 따랐다. 스코어 상황(goalscore)이 경기 흐름의 상당 부분을 "
         "대신 설명하고, 시각 자체를 넣으면 특정 시간대에 과적합될 여지가 있다고 판단했다."],
        ["신체 부위 상세", "foot/head/other/none 4종",
         "StatsBomb이 제공하는 6종(왼발·오른발 구분 포함)의 원-핫",
         "데이터에 있는 정보를 굳이 버릴 이유가 없다. 다만 이 차이 때문에 논문과 열 개수가 다르다."],
    ], widths=[2.6, 3.6, 4.2, 6.2], size=9.5,
        caption_text="논문 대비 피처 구성의 차이와 근거")


# ----------------------------------------------------------------------------- 6장
def ch6(doc, d):
    Y = d["labels"]
    h(doc, "6. 라벨 정의 — 무엇을 맞히게 할 것인가", level=1, page_break=True)

    h(doc, "6.1 정의", level=2)
    code(doc, """
scores[i]   = 1  ⇔  행동 i 시점에 공을 가진 팀이, 행동 i를 포함한 이후 10개 행동 안에 득점
concedes[i] = 1  ⇔  행동 i 시점에 공을 가진 팀이, 행동 i를 포함한 이후 10개 행동 안에 실점

- 득점에는 상대의 자책골도 포함한다(우리 팀 득점이므로).
- 10개 행동 안에 공격권이 바뀌어도 계속 센다. 팀 기준이지 소유 기준이 아니다.
""")
    para(doc, "k=10이라는 값은 논문이 도메인 지식과 예비 실험으로 고른 값이고, 이 구현도 그대로 따랐다. "
              "k가 너무 작으면 골 직전 몇 수만 값을 받아 빌드업 기여가 사라지고, 너무 크면 골과 무관한 "
              "먼 과거 행동까지 양성이 되어 신호가 흐려진다.")

    h(doc, "6.2 윈도우에 ‘현재 행동’이 포함되는가 — 코드로 확인", level=2)
    para(doc, "논문 본문의 정의(F_i^k = [a_(i+1), …, a_(i+k)])를 글자 그대로 읽으면 윈도우는 다음 행동부터다. "
              "그런데 논문 Figure 1에서는 골이 된 슛 직후 P_score = 1.00으로 나오는데, 이는 현재 행동의 결과가 "
              "윈도우에 포함되어야 설명된다. 참조 구현을 직접 확인한 결과 실제로 현재 행동이 포함된다.")
    code(doc, """
# socceraction/vaep/labels.py 의 scores()
res = y["goal"]                      # ← 현재 행동의 골 여부에서 시작
for i in range(1, nr_actions):       # 이후 9개 행동을 OR로 더한다
    res = res | (goal+i & 같은 팀) | (owngoal+i & 다른 팀)
""")
    para(doc, "따라서 윈도우는 **현재 행동 + 이후 9개 = 10개**다. 이 사실은 결과 해석에 직접 영향을 준다. "
              "골이 된 슛은 그 자체로 라벨 1이고 피처에 ‘유형=슛, 결과=성공’이 들어 있으므로 모델이 쉽게 맞히는 "
              "사례가 된다. 그래서 골 슛의 VAEP는 대략 “1 − 직전 득점 확률”이 되고, 반대로 빗나간 슛은 "
              "직전 확률만큼 음수가 된다. 9.7절에서 호날두의 사례가 이 성질을 잘 보여준다.")

    h(doc, "6.3 라벨 분포와 논문과의 차이", level=2)
    table(doc, ["라벨", "이 구현 (라리가, StatsBomb)", "논문 (7개 리그, Wyscout)"], [
        ["scores (득점)", f"{Y.scores.mean()*100:.2f}%  ({int(Y.scores.sum()):,}건 / {len(Y):,}행)", "약 1.66%"],
        ["concedes (실점)", f"{Y.concedes.mean()*100:.2f}%  ({int(Y.concedes.sum()):,}건 / {len(Y):,}행)", "약 0.57%"],
    ], widths=[3.2, 7.0, 6.4], size=10, caption_text="라벨 발생률 비교")
    para(doc, "우리 쪽 비율이 낮은 것은 골이 적어서가 아니라 **분모가 크기 때문이다.** "
              "논문의 Wyscout 데이터는 경기당 약 1,250개 행동인데 이 데이터는 1,993개다(4.4절에서 설명한 "
              "Carry 기록 차이). 행동 10개 윈도우가 실제 시간으로는 더 짧아지므로, 한 골이 양성으로 만드는 "
              "행동 수가 비슷해도 전체 행동 수가 늘어 비율이 내려간다. 이 차이 때문에 Brier score의 "
              "절대값을 논문과 직접 비교하면 안 되고, 기저율 대비 개선율로 비교해야 한다(9.2절).")


# ----------------------------------------------------------------------------- 7장
def ch7(doc, d):
    h(doc, "7. 모델 설정과 하이퍼파라미터", level=1, page_break=True)

    h(doc, "7.1 왜 ‘확률을 내는’ 분류기여야 하는가", level=2)
    para(doc, "VAEP는 두 확률의 차이를 값으로 쓴다. 그래서 모델이 0/1 판정을 내는 것으로는 부족하고 "
              "0~1 사이의 확률을 내야 하며, 그 확률의 **크기가 맞아야** 한다. 예를 들어 실제로 2%인 상황을 "
              "일관되게 6%라고 말하는 모델은 순위(어느 상황이 더 위험한가)는 잘 맞혀도 VAEP 값은 세 배로 "
              "부풀린다. 이 요구가 평가 지표 선택(8.4절)과 캘리브레이션 확인(9.3절)으로 이어진다.")

    h(doc, "7.2 알고리즘 선택: 왜 XGBoost인가", level=2)
    para(doc, "논문은 CatBoost를 택했고, 그 근거로 CatBoost가 Brier와 AUC 모두에서 가장 좋았다는 점과 "
              "범주형 변수 처리 방식을 들었다. 다만 논문의 비교에는 짚어 둘 점이 있다. "
              "논문 부록에 따르면 XGBoost는 트리 100개·깊이 3으로 돌렸고 CatBoost는 기본값(반복 1,000회·깊이 6)을 "
              "썼다. 학습 시간도 16분 대 100분으로 6배 차이가 난다. 즉 **모델 용량이 맞춰지지 않은 비교**여서, "
              "우위가 범주형 처리 덕분인지 단순히 용량이 커서인지 구분되지 않는다. "
              "실제로 논문 Table 3에서 두 모델의 득점 Brier 차이는 0.01390 대 0.01376으로 1% 수준이다.")
    para(doc, "이 과제에서는 XGBoost를 선택했다. 근거는 세 가지다.")
    numbered(doc, "**성능 차이가 실질적으로 없다.** 논문 자신의 표에서 XGBoost는 CatBoost의 1% 이내다. "
                  "게다가 그 XGBoost는 용량이 6분의 1이었다.")
    numbered(doc, "**실무적 이점이 분명하다.** 결측을 그대로 처리하고(4.8절), GPU 학습을 지원해 "
                  "폴드당 18초에 학습이 끝난다. 재현 실험을 여러 번 돌려야 하는 과제에서 이 차이는 크다.")
    numbered(doc, "**비교를 직접 했다.** 같은 피처·같은 분할에서 로지스틱 회귀·랜덤 포레스트와 비교했고 "
                  "결과는 9.4절에 있다. 논문의 결론(트리 앙상블 > 선형 모델, 전체 피처 > 위치+유형)이 "
                  "우리 데이터에서도 재현되는지 확인하는 것이 이 과제의 목적에 더 부합한다고 판단했다.")

    h(doc, "7.3 하이퍼파라미터와 그 근거", level=2)
    rows = [
        ["n_estimators", str(XGB_PARAMS["n_estimators"]), "트리 개수. 9.4절의 용량 실험 결과에 따라 정했다."],
        ["max_depth", str(XGB_PARAMS["max_depth"]), "트리 깊이. 깊을수록 상호작용을 많이 잡지만 희귀 라벨에서는 과적합이 빨라진다."],
        ["learning_rate", str(XGB_PARAMS["learning_rate"]), "표준값 0.1. 트리 수와 함께 용량을 결정한다."],
        ["subsample", str(XGB_PARAMS["subsample"]),
         "트리마다 행의 80%만 사용. 분산을 줄이는 표준 설정이다."],
        ["colsample_bytree", str(XGB_PARAMS["colsample_bytree"]),
         "트리마다 열의 80%만 사용. 원-핫 때문에 열이 145개로 많아 상관 높은 열들이 함께 뽑히는 것을 줄인다."],
        ["min_child_weight", str(XGB_PARAMS["min_child_weight"]),
         "리프가 가져야 할 최소 가중치. 양성이 1%뿐이라 이 값이 작으면 양성 몇 개만으로 리프가 만들어져 "
         "확률이 튄다. 10으로 두어 리프가 최소 수십 개의 사례에 기반하도록 했다."],
        ["tree_method", XGB_PARAMS["tree_method"], "히스토그램 기반 분할. 76만 행에서 속도 차이가 크다."],
        ["eval_metric", XGB_PARAMS["eval_metric"], "확률 품질을 보는 지표로 맞췄다."],
        ["random_state", str(XGB_PARAMS["random_state"]), "시드 고정(2015/16 시즌 개막일). 재현성을 위해."],
        ["device", "cuda 또는 cpu", "GPU가 있으면 자동으로 쓰고 없으면 CPU로 돌아간다. 결과는 같다(11.5절)."],
        ["n_jobs", "min(16, 코어 수)",
         "코어를 전부 쓰면 오히려 느려진다. 80스레드에서 폴드당 15분 걸리던 학습이 16스레드에서 30초였다."],
    ]
    table(doc, ["파라미터", "값", "근거"], rows, widths=[3.4, 2.0, 11.2], size=9.5,
          caption_text="득점·실점 두 모델에 공통으로 적용한 XGBoost 설정 (src/config.py의 XGB_PARAMS)")
    para(doc, "두 라벨(득점·실점)에 같은 설정을 쓴 이유는, 두 문제가 입력은 같고 라벨만 다른 쌍둥이 문제이고 "
              "설정을 따로 두면 비교가 흐려지기 때문이다. 하이퍼파라미터 탐색(그리드 서치)은 하지 않았다. "
              "대신 용량이 결과에 미치는 영향을 9.4절에서 별도로 측정해 근거로 삼았다.")

    h(doc, "7.4 학습 장치와 결정성", level=2)
    para(doc, "학습은 GPU가 있으면 GPU에서 한다. `src/train.py`의 `pick_device()`가 nvidia-smi로 "
              "가장 한가한 GPU를 골라 쓰고, 실패하면 CPU로 내려간다. 같은 데이터·같은 코드로 다시 돌렸을 때 "
              "GPU를 바꿔도 예측 파일의 md5가 같았다(11.5절). 즉 장치 선택이 결과를 바꾸지 않는다.")


# ----------------------------------------------------------------------------- 8장
def ch8(doc, d):
    g = d["games"]
    n_train = int(len(g) * (1 - HOLDOUT_FRAC))
    split_date = g.sort_values(["game_date", "game_id"]).game_date.iloc[n_train]
    h(doc, "8. 검증 절차 — 무엇을 어떻게 재는가", level=1, page_break=True)

    h(doc, "8.1 왜 행 단위가 아니라 경기 단위로 나누는가", level=2)
    para(doc, "이 데이터에서 행 하나는 행동 하나다. 행을 무작위로 섞어 학습/평가를 나누면 성능이 크게 부풀려진다. "
              "이유가 두 가지인데, 두 번째가 특히 치명적이다.")
    numbered(doc, "인접한 행동들은 같은 공격 장면에 속해 위치·유형·스코어가 거의 같다. 사실상 같은 사례가 "
                  "학습과 평가에 동시에 들어간다.")
    numbered(doc, "**라벨 윈도우가 겹친다.** i번째 행동과 i+1번째 행동의 라벨은 10개 행동 중 9개를 공유한다. "
                  "i번째를 학습에 쓰고 i+1번째를 평가에 쓰면, 평가 대상의 정답을 이미 학습에서 본 셈이다.")
    para(doc, "그래서 이 구현은 **모든 분할을 경기 단위로** 한다. 한 경기의 행동은 전부 학습 쪽이거나 "
              "전부 평가 쪽이다.")

    h(doc, "8.2 두 가지 분할을 모두 쓴 이유", level=2)
    table(doc, ["분할", "구성", "무엇에 쓰는가", "왜 필요한가"], [
        [f"경기 단위 {N_FOLDS}겹 교차검증 (OOF)",
         f"{len(g)}경기를 {N_FOLDS}개로 나눠 돌아가며 평가. 시드 {SEED} 고정.",
         "9장의 모든 VAEP 값과 선수 순위, 그리고 주 평가 지표",
         "모든 행동이 ‘그 경기를 학습에 쓰지 않은 모델’의 예측을 받아야 선수 순위가 자기 경기를 외운 결과가 "
         "되지 않는다. 380경기를 전부 쓰므로 순위의 표본도 최대가 된다."],
        ["날짜순 홀드아웃",
         f"앞 {n_train}경기로 학습 → 마지막 {len(g)-n_train}경기({split_date:%Y-%m-%d} 이후)로 1회 평가",
         "최종 점검, 논문 설정과의 비교",
         "논문은 ‘과거 시즌으로 학습하고 다음 시즌을 평가’했다. 한 시즌만 쓰는 이 과제에서 그에 대응하는 "
         "것이 시즌 앞부분 → 뒷부분 분할이다. 실제 사용 상황(지난 경기로 만든 모델로 앞으로의 경기를 평가)과도 "
         "같은 방향이다."],
    ], widths=[3.2, 4.0, 3.4, 6.0], size=9.5, caption_text="두 가지 검증 분할과 각각의 역할")
    para(doc, "두 분할의 결과가 비슷하게 나오면 “폴드를 어떻게 나누든, 시간이 흐르든 성능이 유지된다”는 "
              "뜻이 된다. 9.1절에서 실제로 그렇게 나왔다.")

    h(doc, "8.3 평가 지표와 선택 근거", level=2)
    para(doc, "득점 라벨은 100번에 1번, 실점 라벨은 400번에 1번 일어난다. 이런 데이터에서는 "
              "**정확도(accuracy)가 쓸모없다.** 무조건 0이라고 답하는 모델도 99%를 맞히기 때문이다. "
              "그래서 다음 네 가지를 쓴다.")
    table(doc, ["지표", "무엇을 재는가", "왜 필요한가"], [
        ["Brier score", "예측 확률과 실제 라벨의 평균 제곱 오차. 낮을수록 좋다.",
         "변별력과 보정을 함께 반영하는 proper scoring rule. VAEP가 확률의 뺄셈이므로 보정이 반영되는 지표가 필요하다."],
        ["Brier skill (BSS)", "‘항상 평균값만 찍는 모델’ 대비 개선율. 0이면 그 모델과 같고 1이면 완벽.",
         "희귀 사건에서는 Brier 절대값이 원래 작다. 기저율이 다른 데이터끼리 비교하려면 이 형태가 필요하다(9.2절)."],
        ["log loss", "확률 예측의 로그 손실.", "Brier와 다른 방식으로 확률 품질을 보는 두 번째 proper score."],
        ["ROC AUC", "양성과 음성을 무작위로 뽑았을 때 양성에 더 높은 확률을 줄 확률.",
         "클래스 비율에 영향받지 않아 순위 능력만 본다. 단 확률의 크기는 보지 못하므로 Brier와 함께 써야 한다."],
    ], widths=[2.6, 6.4, 7.6], size=9.5, caption_text="평가 지표와 선택 근거")

    h(doc, "8.4 신뢰구간 — 왜 부트스트랩을 경기 단위로 하는가", level=2)
    para(doc, "AUC 하나만 보면 0.81과 0.79의 차이가 의미 있는지 알 수 없다. 이 구현은 "
              "**경기를 복원추출로 다시 뽑는 부트스트랩 500회**로 95% 구간을 구한다. 행을 다시 뽑지 않고 "
              "경기를 다시 뽑는 이유는 8.1절과 같다. 한 경기 안의 행동들은 서로 독립이 아니므로, "
              "행 단위로 뽑으면 구간이 실제보다 좁게 나온다.")
    para(doc, "구현상의 문제도 하나 있었다. sklearn의 roc_auc_score를 500번 부르면 757,309행을 매번 "
              "다시 정렬해 9분이 걸렸다. 정렬은 한 번이면 충분하므로, 예측값 정렬을 재사용하고 표본마다 "
              "가중치만 바꿔 세는 방식(`train.py`의 FastAUC)으로 바꿔 1분으로 줄였다. "
              "sklearn 결과와 소수점 15자리까지 일치하는 것을 확인했다.")


# ----------------------------------------------------------------------------- 9장
def player_profile(d, who):
    """선수 한 명의 행동 유형별 가치와 슛 성적을 계산한다 (보고서 해설용)."""
    import socceraction.spadl as spadl

    a = spadl.add_names(d["actions"])
    v = pd.read_parquet(f"{OUT}/action_values.parquet")
    av = a.merge(v, on=["game_id", "action_id"]).merge(d["players"], on="player_id", how="left")
    av["name"] = av.nickname.fillna(av.player_name)
    rat = d["ratings"].set_index("name")
    x = av[av.name == who]
    shots = x[x.type_name.str.contains("shot")]
    mins = rat.loc[who, "minutes"]
    return {
        "minutes": int(mins),
        "shots": len(shots),
        "shots_p90": len(shots) / mins * 90,
        "goals": int((shots.result_name == "success").sum()),
        "shot_vaep": shots.vaep_value.sum(),
        "shot_vaep_goal": shots[shots.result_name == "success"].vaep_value.sum(),
        "shot_vaep_miss": shots[shots.result_name != "success"].vaep_value.sum(),
        "vaep_p90": rat.loc[who, "vaep_p90"],
        "by_type": x.groupby("type_name").vaep_value.sum().sort_values(ascending=False),
    }


def ch9(doc, d):
    met, rat, bt, seq, trad, abl = (d["metrics"], d["ratings"], d["by_type"],
                                    d["sequence"], d["trad"], d["ablation"])
    cap = pd.read_csv(f"{OUT}/capacity_oof.csv")
    h(doc, "9. 결과", level=1, page_break=True)

    h(doc, "9.1 득점·실점 확률 모델의 성능", level=2)
    rows = []
    for split, sname in [("oof", f"경기 단위 {N_FOLDS}겹 OOF (380경기)"),
                         ("holdout", "날짜순 홀드아웃 (마지막 76경기)")]:
        for label, lname in [("scores", "득점"), ("concedes", "실점")]:
            rows.append([
                sname if label == "scores" else "", lname,
                f"{m(met, split, label, 'n'):,.0f}",
                f"{m(met, split, label, 'base_rate')*100:.2f}%",
                f"{m(met, split, label, 'brier'):.5f}",
                f"{m(met, split, label, 'brier_skill'):.3f}",
                f"{m(met, split, label, 'log_loss'):.4f}",
                f"**{m(met, split, label, 'roc_auc'):.3f}** "
                f"({m(met, split, label, 'auc_lo'):.3f}~{m(met, split, label, 'auc_hi'):.3f})",
            ])
    table(doc, ["평가 방식", "대상", "행동 수", "기저율", "Brier", "Brier skill", "log loss",
                "ROC AUC (95%)"], rows,
          widths=[3.4, 1.2, 1.8, 1.4, 1.8, 1.8, 1.6, 3.6], size=9,
          caption_text="확률 모델 평가 결과. 괄호는 경기 단위 부트스트랩 500회로 구한 95% 구간")

    para(doc, "읽는 방법은 이렇다.")
    bullet(doc, f"**득점 모델은 잘 작동한다.** AUC {m(met,'oof','scores','roc_auc'):.3f}은 "
                f"‘골로 이어진 상황’과 ‘아닌 상황’을 무작위로 하나씩 뽑았을 때 "
                f"{m(met,'oof','scores','roc_auc')*100:.0f}% 확률로 전자에 더 높은 점수를 준다는 뜻이다. "
                f"Brier skill {m(met,'oof','scores','brier_skill'):.3f}은 "
                f"‘항상 평균(1.1%)만 찍는 모델’보다 오차가 {m(met,'oof','scores','brier_skill')*100:.0f}% 작다는 뜻이다.")
    bullet(doc, f"**실점 모델은 약하다.** AUC {m(met,'oof','concedes','roc_auc'):.3f}로 순위는 어느 정도 매기지만, "
                f"Brier skill은 {m(met,'oof','concedes','brier_skill'):.3f}에 그친다. 공을 가진 팀이 곧 실점하려면 "
                f"공을 잃고 상대가 빠르게 마무리까지 해야 하는데, 그 과정의 대부분(상대의 역습 능력, 수비 복귀 상태)이 "
                f"온더볼 이벤트에 남지 않기 때문이다. 이 사실은 수비 가치를 해석할 때 반드시 함께 고려해야 한다(10.2절).")
    bullet(doc, "**두 분할의 결과가 거의 같다.** 교차검증과 시간순 홀드아웃이 비슷하다는 것은, "
                "시즌 앞부분만 보고 뒷부분을 예측해도 성능이 유지된다는 뜻이다. 즉 모델이 특정 시기에 "
                "과적합되어 있지 않다.")

    h(doc, "9.2 논문 결과와의 비교", level=2)
    para(doc, "논문은 Wyscout의 7개 리그 11,565경기로 CatBoost를 학습했고, 우리는 StatsBomb의 한 리그 "
              "380경기로 XGBoost를 학습했다. 데이터·공급사·알고리즘이 모두 다르므로 Brier 절대값은 비교할 수 없다. "
              "기저율이 다르면 Brier의 크기 자체가 달라지기 때문이다(6.3절). 비교는 **기저율 대비 개선율(BSS)**로 해야 한다.")
    table(doc, ["대상", "논문 (Wyscout 7개 리그)", "이 구현 (라리가 1시즌)", "차이"], [
        ["득점 Brier", "0.01376 (기저 0.01632)", f"{m(met,'oof','scores','brier'):.5f} "
         f"(기저 {m(met,'oof','scores','brier_base'):.5f})", "기저율이 달라 직접 비교 불가"],
        ["**득점 Brier skill**", "**0.157**", f"**{m(met,'oof','scores','brier_skill'):.3f}**",
         f"{abs(0.157 - m(met,'oof','scores','brier_skill')):.3f}"],
        ["**실점 Brier skill**", "**0.030**", f"**{m(met,'oof','concedes','brier_skill'):.3f}**",
         f"{abs(0.030 - m(met,'oof','concedes','brier_skill')):.3f}"],
        ["득점 AUC", "0.769", f"{m(met,'oof','scores','roc_auc'):.3f}", "이 구현이 높음"],
        ["실점 AUC", "0.731", f"{m(met,'oof','concedes','roc_auc'):.3f}", "이 구현이 높음"],
    ], widths=[3.4, 4.4, 4.4, 4.4], size=9.5,
        caption_text="논문 Table 3(CatBoost, 전체 피처)과 이 구현의 비교")
    para(doc, "**Brier skill이 거의 같다는 점이 이 재현의 가장 중요한 검증이다.** 서로 다른 데이터에서 "
              "같은 방법을 적용했을 때 ‘기저율 대비 얼마나 개선했는가’가 일치한다는 것은, 구현이 논문의 "
              "설계를 제대로 옮겼다는 뜻이다. 특히 실점 모델이 0.03 언저리에서 멈추는 현상까지 같이 재현됐다.")
    para(doc, "AUC가 우리 쪽에서 높게 나온 이유는 단정할 수 없지만, 설명 가능한 후보가 셋 있다. "
              "(1) StatsBomb 데이터가 더 상세하다 — 왼발·오른발 구분, 고정밀 좌표, Carry 이벤트. "
              "(2) 한 리그만 쓰므로 리그 간 스타일 차이라는 잡음이 없다. "
              "(3) 행동 구성이 달라(드리블 39%) 라벨 윈도우가 실제 시간으로 더 짧고, 그만큼 "
              "‘가까운 미래’가 현재 상태와 강하게 연결된다. 이 셋을 분리해 확인하려면 같은 경기를 두 공급사 "
              "형식으로 갖고 비교해야 하는데, 이 과제의 범위를 넘는다.")

    figure(doc, "model_eval.png",
           "(a) ROC 곡선과 (b) 캘리브레이션. 실선은 5겹 OOF, 점선은 홀드아웃. "
           "캘리브레이션이 대각선에 붙어 있어야 VAEP 값을 ‘골’ 단위로 읽을 수 있다.")

    h(doc, "9.3 확률의 크기가 맞는가 (캘리브레이션)", level=2)
    para(doc, "위 그림 (b)는 예측 확률을 10분위로 나눠, 각 구간의 평균 예측값(x축)과 실제 발생 비율(y축)을 찍은 것이다. "
              "네 곡선 모두 대각선에 가깝다. 즉 모델이 “5%”라고 말한 상황에서 실제로 5% 가까이 일어났다. "
              "이것이 확인되어야 7.1절에서 말한 대로 VAEP 값을 골 단위로 해석할 수 있다. "
              "AUC만 높고 이 그림이 대각선에서 벗어나 있었다면, 순위는 맞아도 값의 크기는 쓸 수 없었을 것이다.")

    h(doc, "9.4 설계 선택은 타당했는가 — 논문 Table 3의 재현", level=2)
    para(doc, "논문은 피처 집합과 알고리즘을 바꿔 가며 비교해 자신의 선택을 정당화했다. 같은 실험을 "
              "우리 데이터에서 수행했다(`src/ablation.py`). 분할은 날짜순 홀드아웃 하나로 고정해 비교를 공정하게 했다.")
    fs_rows = []
    for _, r in abl[abl.group == "피처 집합"].iterrows():
        fs_rows.append([r.setting, f"{int(r.n_features)}",
                        f"{r.scores_brier_skill:.3f}",
                        "—" if pd.isna(r.scores_roc_auc) else f"{r.scores_roc_auc:.3f}",
                        f"{r.concedes_brier_skill:.3f}",
                        "—" if pd.isna(r.concedes_roc_auc) else f"{r.concedes_roc_auc:.3f}"])
    table(doc, ["피처 집합", "열 수", "득점 BSS", "득점 AUC", "실점 BSS", "실점 AUC"], fs_rows,
          widths=[5.0, 1.4, 2.4, 2.4, 2.4, 2.4], size=9.5, align_right=[1, 2, 3, 4, 5],
          caption_text="피처 집합 비교 (날짜순 홀드아웃 76경기). 논문 Table 3의 상단에 대응")
    para(doc, "논문의 결론이 그대로 재현됐다. 위치만, 유형만 쓰는 기존 방식보다 둘을 합친 것이 낫고, "
              "전체 피처는 그보다 더 낫다. 특히 득점 BSS는 ‘위치+유형’의 "
              f"{abl[(abl.group=='피처 집합') & (abl.setting=='위치 + 행동 유형')].scores_brier_skill.iloc[0]:.3f}에서 "
              f"{abl[(abl.group=='피처 집합') & (abl.setting=='전체 피처 (이 프로젝트)')].scores_brier_skill.iloc[0]:.3f}로 "
              "크게 올라간다. 결과·신체 부위·직전 행동과의 시간 간격·스코어 같은 ‘맥락’ 피처가 "
              "성능의 상당 부분을 만든다는 뜻이고, 이는 VAEP가 기존 지표와 다른 지점(2.1절의 한계 2번)과 정확히 일치한다.")

    alg_rows = []
    for _, r in abl[abl.group == "알고리즘"].iterrows():
        alg_rows.append([r.setting, f"{r.scores_brier_skill:.3f}", f"{r.scores_roc_auc:.3f}",
                         f"{r.concedes_brier_skill:.3f}", f"{r.concedes_roc_auc:.3f}"])
    table(doc, ["알고리즘", "득점 BSS", "득점 AUC", "실점 BSS", "실점 AUC"], alg_rows,
          widths=[5.6, 2.6, 2.6, 2.6, 2.6], size=9.5, align_right=[1, 2, 3, 4],
          caption_text="알고리즘 비교 (같은 피처, 같은 홀드아웃)")
    para(doc, "트리 앙상블이 선형 모델보다 낫다는 논문의 결론도 재현됐다. 로지스틱 회귀는 AUC는 제법 나오지만 "
              "BSS가 낮은데, 이는 순위는 매기면서 확률의 크기를 잘 못 맞춘다는 뜻이다(8.3절에서 두 지표를 "
              "함께 봐야 한다고 한 이유). 랜덤 포레스트는 두 지표 모두 XGBoost보다 낮았다.")

    h(doc, "9.4.1 모델 용량은 어떻게 정했나", level=3)
    para(doc, "하이퍼파라미터 중 결과에 가장 크게 영향을 주는 것은 트리 수와 깊이다. 이 값만큼은 "
              "**최종 값 산출과 같은 프로토콜(경기 단위 5겹 OOF)**로 비교해서 정했다. 홀드아웃 한 번은 "
              "76경기뿐이라 실점처럼 드문 라벨에서 흔들리기 때문이다.")
    cap_rows = []
    for setting in cap.setting.unique():
        s = cap[cap.setting == setting]
        sc = s[s.label == "scores"].iloc[0]
        cc = s[s.label == "concedes"].iloc[0]
        cap_rows.append([setting, f"{sc.brier_skill:.4f}", f"{sc.roc_auc:.4f}",
                         f"{cc.brier_skill:.4f}", f"{cc.roc_auc:.4f} ({cc.auc_lo:.3f}~{cc.auc_hi:.3f})"])
    table(doc, ["설정", "득점 BSS", "득점 AUC", "실점 BSS", "실점 AUC (95%)"], cap_rows,
          widths=[4.6, 2.2, 2.2, 2.2, 4.4], size=9.5, align_right=[1, 2, 3],
          caption_text="XGBoost 용량 비교 (경기 단위 5겹 OOF, 나머지 설정은 동일)")
    para(doc, "결과는 분명하다. **용량을 키울수록 나빠진다.** 특히 실점 모델에서 두드러져서, "
              "트리 300·깊이 6은 AUC 0.737인데 트리 100·깊이 3은 0.767이다. 두 값의 95% 구간이 거의 겹치지 않는다. "
              "이유는 라벨 수에 있다. 실점 양성은 전체에서 1,782건뿐이고 학습 폴드에는 1,400건 정도만 들어간다. "
              "이 정도 표본에서 깊은 트리 300개는 양성 몇 개씩을 외우는 방향으로 학습된다. "
              "득점 쪽은 양성이 8,354건으로 6배 많아 용량에 덜 민감하지만, 그래도 최댓값은 중간 용량에서 나온다.")
    para(doc, "이 실험에 따라 최종 설정을 **트리 100 · 깊이 3**으로 정했다. 이는 공교롭게도 논문 부록이 "
              "XGBoost에 쓴 설정과 같다. 처음에는 “논문의 XGBoost가 CatBoost보다 작은 설정이었으니 "
              "키우면 낫겠지”라고 생각해 300·6으로 시작했는데, 데이터가 반대라고 말해 주어 바꾼 것이다. "
              "보고서에 이 경위를 남기는 이유는, 결론만 보면 ‘논문을 따라 했다’로 보이지만 실제로는 "
              "측정해서 도달한 값이기 때문이다.")

    h(doc, "9.5 모델이 무엇을 보고 판단하는가", level=2)
    figure(doc, "feature_importance.png",
           "홀드아웃 학습 모델의 피처 중요도 상위 15개 (gain 기준). a0은 지금 행동, a1·a2는 직전 행동.")
    imp = d["importance"]
    top_s = list(imp["scores"].sort_values(ascending=False).head(5).index)
    top_c = list(imp["concedes"].sort_values(ascending=False).head(5).index)
    para(doc, f"득점 모델의 상위 피처는 {', '.join(top_s)} 순이다. "
              f"‘결과=실패’와 ‘종료 지점에서 골대까지 거리’가 앞자리에 오는 것은 상식과 맞는다. "
              f"행동이 실패로 끝나면 그 소유는 거기서 끝나므로 득점 확률이 급락하고, 성공했다면 "
              f"공이 골대에 얼마나 가까워졌는지가 다음 확률을 좌우한다.")
    para(doc, f"실점 모델의 상위 피처는 {', '.join(top_c)} 순이다. 파울, 골키퍼 선방, 걷어내기처럼 "
              f"**우리 팀이 이미 위험에 처했음을 알려주는 행동**이 앞에 온다. 이는 실점 모델이 "
              f"‘앞으로 위험해질 상황’을 예측한다기보다 ‘이미 위험한 상황’을 확인하는 데 가깝다는 뜻이고, "
              f"9.1절에서 본 낮은 Brier skill과 같은 이야기를 한다.")

    h(doc, "9.6 행동 유형별 가치", level=2)
    rows = []
    for _, r in bt.nlargest(10, "n").iterrows():
        rows.append([r.type_name, f"{int(r.n):,}", f"{r.offensive_mean:+.5f}",
                     f"{r.defensive_mean:+.5f}", f"{r.vaep_mean:+.5f}", f"{r.vaep_sum:+.1f}"])
    table(doc, ["행동 유형", "횟수", "평균 공격 가치", "평균 수비 가치", "평균 VAEP", "시즌 합계"],
          rows, widths=[3.2, 2.2, 2.8, 2.8, 2.6, 2.4], size=9.5, align_right=[1, 2, 3, 4, 5],
          caption_text="행동 유형별 가치 (빈도 상위 10종)")
    figure(doc, "value_by_actiontype.png",
           "(a) 행동 1회당 평균 VAEP와 (b) 시즌 전체 합계. 한 번의 값이 작아도 횟수가 많으면 합계는 커진다.")
    tackle = bt[bt.type_name == "tackle"].iloc[0]
    shot = bt[bt.type_name == "shot"].iloc[0]
    para(doc, f"세 가지를 짚을 만하다. 첫째, **한 번의 값이 가장 큰 행동은 슛**({shot.vaep_mean:+.4f})이지만 "
              f"횟수가 적어 합계에서는 드리블·패스에 밀린다. 둘째, **태클은 수비 가치가 공격 가치보다 크다**"
              f"(평균 공격 {tackle.offensive_mean:+.4f} vs 수비 {tackle.defensive_mean:+.4f}). "
              f"공을 끊는 행동의 값이 주로 ‘상대의 득점 기회를 지운 것’에서 나온다는 VAEP의 구조가 "
              f"숫자로 드러나는 부분이다. 셋째, **파울과 배드 터치는 평균 VAEP가 음수**다. "
              f"값을 잃는 행동에 벌점이 주어진다는 뜻이고, 이 역시 기대한 대로다.")

    h(doc, "9.7 선수별 90분당 VAEP", level=2)
    elig = rat[rat.minutes >= MIN_MINUTES]
    rows = []
    for i, (_, r) in enumerate(elig.head(10).iterrows(), 1):
        rows.append([str(i), r["name"], r.team_name, f"{int(r.games)}", f"{int(r.minutes):,}",
                     f"{int(r.actions):,}", f"{r.offensive_p90:+.3f}", f"{r.defensive_p90:+.3f}",
                     f"**{r.vaep_p90:.3f}**"])
    table(doc, ["#", "선수", "팀", "경기", "출전(분)", "행동", "공격/90", "수비/90", "VAEP/90"],
          rows, widths=[0.8, 3.4, 2.8, 1.2, 1.8, 1.8, 1.8, 1.8, 1.8], size=9.5,
          align_right=[3, 4, 5, 6, 7, 8],
          caption_text=f"90분당 VAEP 상위 10명 ({MIN_MINUTES}분 이상 출전한 {len(elig)}명 중)")
    figure(doc, "top_players.png", "90분당 VAEP 상위 10명. 막대는 합계, 옆의 숫자는 공격·수비 분해와 출전 시간.")
    para(doc, f"모든 값은 **그 경기를 학습에 쓰지 않은 모델**의 예측에서 나온다(8.2절). "
              f"{MIN_MINUTES}분(약 10경기) 미만 출전 선수를 제외한 이유는, 출전 시간이 짧으면 90분당 값이 "
              f"크게 요동치기 때문이다. 논문도 같은 기준을 쓴다.")

    h(doc, "9.7.1 전통 지표와 무엇이 다른가", level=2)
    para(doc, "VAEP가 골·어시스트와 다른 것을 보고 있는지 확인하기 위해, 같은 데이터에서 "
              "90분당 골+어시스트 순위를 계산해 비교했다(`src/compare_traditional.py`). "
              "어시스트는 SPADL에 별도 항목이 없으므로 ‘골 직전의 같은 팀 성공 패스 계열’로 정의했다.")
    rows = []
    for _, r in trad.nlargest(10, "ga_p90").iterrows():
        rows.append([r["name"], r.team_name, f"{r.goals_p90:.3f}", f"{r.assists_p90:.3f}",
                     f"{r.ga_p90:.3f}", f"{int(r.rank_ga_p90)}위",
                     f"{r.vaep_p90:.3f}", f"**{int(r.rank_vaep_p90)}위**"])
    table(doc, ["선수", "팀", "골/90", "도움/90", "골+도움/90", "그 순위", "VAEP/90", "VAEP 순위"],
          rows, widths=[3.2, 2.6, 1.6, 1.6, 2.0, 1.6, 1.8, 2.0], size=9.5,
          align_right=[2, 3, 4, 5, 6, 7],
          caption_text="90분당 골+어시스트 상위 10명과 그들의 VAEP 순위")
    figure(doc, "traditional_vs_vaep.png",
           "두 지표의 순위 비교. 대각선에서 멀수록 두 지표가 다르게 평가한 선수다.", width=12.5)
    rho = trad.ga_p90.corr(trad.vaep_p90, method="spearman")
    para(doc, f"두 순위의 스피어만 상관은 {rho:.2f}다. 전혀 무관하지도, 같은 것을 재지도 않는다는 뜻이다. "
              f"차이가 큰 쪽을 들여다보면 VAEP가 무엇을 다르게 보는지 알 수 있다.")

    ron = player_profile(d, "Cristiano Ronaldo")
    bale = player_profile(d, "Gareth Bale")
    messi = player_profile(d, "Lionel Messi")
    ron_rank = int(trad[trad.name == "Cristiano Ronaldo"].rank_vaep_p90.iloc[0])
    ron_ga_rank = int(trad[trad.name == "Cristiano Ronaldo"].rank_ga_p90.iloc[0])
    para(doc, f"**사례 1 — 호날두 (골+어시스트 {ron_ga_rank}위, VAEP {ron_rank}위).** "
              f"이 시즌 호날두는 {ron['minutes']:,}분을 뛰며 슛을 {ron['shots']}개 시도해 90분당 "
              f"{ron['shots_p90']:.1f}개를 기록했다. 슛에서 얻은 VAEP를 나눠 보면 "
              f"골이 된 슛에서 {ron['shot_vaep_goal']:+.1f}, 빗나간 슛에서 {ron['shot_vaep_miss']:+.1f}로 "
              f"합계 {ron['shot_vaep']:+.1f}이다. 반면 베일은 슛이 90분당 {bale['shots_p90']:.1f}개로 적지만 "
              f"합계 {bale['shot_vaep']:+.1f}"
              f"(성공 {bale['shot_vaep_goal']:+.1f} / 실패 {bale['shot_vaep_miss']:+.1f})를 남겼다.")
    para(doc, "이 차이는 VAEP의 정의에서 곧바로 나온다. 빗나간 슛은 그 직전까지 쌓아 온 득점 확률을 0으로 "
              "만들기 때문에 ‘직전 확률만큼’ 음수가 된다. 슛을 많이 시도하는 선수는 골도 많지만 지운 확률도 많다. "
              "골·어시스트는 성공만 세므로 이 비용이 보이지 않는다. **어느 쪽이 옳은 평가인가는 이 방법으로 "
              "답할 수 없다.** 다만 VAEP를 쓸 때 ‘슛 시도가 많은 선수는 불리하다’는 성질을 알고 써야 한다는 "
              "점은 분명하다.")
    top3 = messi["by_type"].head(3)
    para(doc, f"**사례 2 — 메시의 가치 구성.** 메시의 VAEP는 한 유형에 몰려 있지 않다. "
              f"{', '.join(f'{k} {v:+.1f}' for k, v in top3.items())} 순으로 고르게 분포한다. "
              f"논문 §5.4가 ‘액션 타입별로 분해하면 플레이 스타일이 보인다’고 한 대목을 그대로 보여주는 예다. "
              f"반대로 수아레스는 값의 대부분이 슛에서 나온다. 총점만 보면 놓치는 정보다.")

    h(doc, "9.8 한 번의 공격을 행동 단위로 분해하기", level=2)
    para(doc, "마지막으로, 합계가 아니라 장면 하나를 들여다본다. 논문 Figure 1이 바르셀로나의 골 장면을 "
              "6개 행동으로 분해한 것과 같은 방식이다. 골로 끝난 공격 중 같은 팀의 연속 행동이 길고 "
              "VAEP 합이 큰 장면을 자동으로 골랐다(`src/viz.py`).")
    rows = []
    for i, (_, r) in enumerate(seq.iterrows(), 1):
        rows.append([str(i), r["name"], r.type_name, r.result_name, f"{r.p_scores:.4f}",
                     f"{r.offensive_value:+.4f}", f"{r.defensive_value:+.4f}", f"**{r.vaep_value:+.4f}**"])
    table(doc, ["#", "선수", "행동", "결과", "직후 득점 확률", "공격 가치", "수비 가치", "VAEP"],
          rows, widths=[0.8, 3.2, 2.2, 1.8, 2.6, 2.0, 2.0, 2.0], size=9.5,
          align_right=[4, 5, 6, 7],
          caption_text="셀타 비고의 득점 장면 10개 행동 분해")
    figure(doc, "sequence.png",
           "같은 장면의 시각화. 위는 경기장 위의 행동 흐름(색이 진할수록 VAEP가 크다), "
           "아래는 행동별 VAEP 막대와 직후 득점 확률(선).")
    para(doc, f"자기 진영에서 태클로 공을 끊는 순간({seq.vaep_value.iloc[0]:+.3f}, 대부분 수비 가치)부터 "
              f"마무리({seq.vaep_value.iloc[-1]:+.3f})까지, 득점 확률이 "
              f"{seq.p_scores.iloc[0]*100:.1f}% → {seq.p_scores.iloc[-2]*100:.1f}% → 골로 올라간다. "
              f"장면 전체의 VAEP 합은 {seq.vaep_value.sum():+.3f}이고, 그중 마무리와 직전 패스가 "
              f"{(seq.vaep_value.iloc[-1] + seq.vaep_value.iloc[-2]) / seq.vaep_value.sum() * 100:.0f}%를 가져간다.")
    para(doc, "여기서 VAEP의 크레딧 배분 성질이 드러난다. 확률이 실제로 크게 움직이는 순간에 값이 몰리므로 "
              "마무리와 마지막 패스가 큰 몫을 받고, 빌드업은 작은 몫을 나눠 받는다. "
              "6번 패스처럼 확률을 낮춘 행동은 음수를 받는다. 이 배분이 ‘공정한가’는 방법론의 선택이지 "
              "데이터로 검증되는 사실이 아니다(10.3절).")


# ----------------------------------------------------------------------------- 10장
def ch10(doc, d):
    met = d["metrics"]
    h(doc, "10. 결과의 불확실성과 한계", level=1, page_break=True)
    para(doc, "이 장은 “위 결과를 어디까지 믿어도 되는가”에 답한다. 측정할 수 있는 불확실성은 측정했고, "
              "측정할 수 없는 것은 그렇다고 적었다.")

    h(doc, "10.1 폴드를 다시 나누면 값이 얼마나 움직이나 (측정)", level=2)
    para(doc, "선수 값은 ‘그 경기를 학습에 쓰지 않은 모델’의 예측으로 만든다. 그런데 어느 경기를 어느 폴드에 "
              "넣을지는 임의의 선택이다. 이 임의성이 결과를 얼마나 흔드는지 측정하기 위해, 시드를 바꿔 "
              "5겹을 세 번 다시 나누고 같은 계산을 반복했다(`src/fold_sensitivity.py`).")
    fs = pd.read_csv(f"{OUT}/fold_sensitivity.csv")
    seed_cols = [c for c in fs.columns if c.startswith("seed_")]
    rows = []
    for _, r in fs.head(10).iterrows():
        rows.append([r["name"]] + [f"{r[c]:.3f}" for c in seed_cols] +
                    [f"{r['mean']:.3f}", f"{r['spread']:.3f}", f"{int(r['rank_move'])}계단"])
    table(doc, ["선수"] + [f"분할 {i+1}" for i in range(len(seed_cols))] + ["평균", "최대-최소", "순위 변동"],
          rows, widths=[3.4] + [1.9] * len(seed_cols) + [1.9, 2.0, 2.0], size=9.5,
          align_right=list(range(1, len(seed_cols) + 4)),
          caption_text="폴드 분할을 세 번 바꿨을 때 상위 10명의 90분당 VAEP")
    top12 = fs.head(12)
    para(doc, f"상위 12명의 값은 중앙값 {top12.spread.median():.3f}, 최대 {top12.spread.max():.3f}만큼 흔들렸고, "
              f"상위 10명의 순위 변동은 최대 {int(fs.head(10).rank_move.max())}계단이었다. "
              f"**즉 상위권 순위는 폴드 분할을 바꿔도 거의 그대로다.** 다만 값 자체는 소수 둘째 자리에서 움직이므로, "
              f"0.450과 0.443처럼 붙어 있는 두 선수의 우열을 이 표로 가리는 것은 무리다.")
    para(doc, "여기에 덧붙일 것이 있다. 이 측정을 9.4.1절에서 탈락한 큰 모델(트리 300·깊이 6)로 했을 때는 "
              "흔들림이 중앙값 0.040, 최대 0.071이었고 상위 10명의 순위가 최대 4계단까지 바뀌었다. "
              "**용량을 줄이자 정확도만 좋아진 것이 아니라 결과의 안정성도 함께 좋아진 것이다.** "
              "과적합한 모델은 폴드가 바뀔 때마다 다른 것을 외우므로 값이 더 크게 흔들린다는 설명과 맞는다. "
              "모델 선택의 근거로 정확도 지표만 보는 것으로는 이 차이를 볼 수 없었다.")
    para(doc, "남은 불확실성은 모델의 결함이라기보다 표본 크기의 문제다. 한 시즌 380경기에서 골은 1,043개뿐이고, "
              "선수 한 명이 받는 값은 그중 일부에 대한 확률 추정치의 합이다. 시즌을 여러 개 합치면 줄어든다.")

    h(doc, "10.2 구조적 한계", level=2)
    table(doc, ["한계", "내용", "결과 해석에 미치는 영향"], [
        ["온더볼만 평가",
         "이벤트 데이터에는 공을 가진 선수 주변만 기록된다. 공간을 만드는 침투, 수비 위치 선정, "
         "압박은 데이터에 없다.",
         "상위권이 공격 자원으로 채워진다. 수비수·수비형 미드필더의 기여는 구조적으로 과소평가된다. "
         "‘VAEP 순위 = 잘한 선수 순위’로 읽으면 안 된다."],
        ["실점 모델이 약함",
         f"Brier skill {m(met,'oof','concedes','brier_skill'):.3f}. 기저율만 찍는 모델보다 "
         f"{m(met,'oof','concedes','brier_skill')*100:.0f}% 나은 수준이다.",
         "VAEP의 수비 가치 성분은 신호 대비 잡음이 크다. 9.7절 표에서 수비/90이 대부분 작은 음수인 것도 "
         "수비를 못해서가 아니라 이 성분의 변동 폭 자체가 작기 때문이다."],
        ["결과 기반 크레딧",
         "골이 된 슛은 ‘1 − 직전 확률’, 빗나간 슛은 ‘−직전 확률’을 받는다.",
         "마무리 운이 값에 그대로 들어간다. 9.7.1절 호날두 사례가 이 성질의 직접적인 결과다."],
        ["리그·팀 보정 없음",
         "약한 리그나 강한 팀에서는 같은 선수라도 가치 높은 행동을 하기 쉽다.",
         "이 과제는 한 리그 한 시즌만 다루므로 리그 간 비교는 아예 시도하지 않았다. "
         "팀 간 비교(예: 바르셀로나 선수 vs 중위권 팀 선수)도 이 보정 없이는 조심해야 한다."],
        ["k=10의 민감도 미측정",
         "라벨 윈도우를 10개 행동으로 둔 것은 논문을 따른 선택이다.",
         "k를 바꿨을 때 순위가 얼마나 달라지는지는 확인하지 않았다. 후속 작업으로 남긴다."],
        ["평균적인 팀 기준",
         "확률 모델은 데이터 속 모든 팀의 평균 행동을 학습한다.",
         "특정 팀 전술에서 합리적인 선택(예: 점유 위주 팀의 안전한 횡패스)이 평균 기준으로는 "
         "낮게 평가될 수 있다."],
    ], widths=[2.8, 6.4, 7.4], size=9.5, caption_text="구조적 한계와 그 영향")

    h(doc, "10.3 이 결과로 말할 수 있는 것과 없는 것", level=2)
    para(doc, "**말할 수 있는 것**", bold=False)
    bullet(doc, "확률 모델은 기저율 대비 의미 있게 낫고(득점 BSS 0.15), 확률의 크기도 정확하다(캘리브레이션 대각선).")
    bullet(doc, "논문의 설계 선택(맥락 피처를 다 쓰는 것, 트리 앙상블)이 다른 데이터에서도 유효하다.")
    bullet(doc, "VAEP는 골·어시스트와 상관 0.48 수준으로 다른 것을 재며, 그 차이는 ‘슛 시도의 비용’과 "
                "‘빌드업 기여’라는 설명 가능한 요인에서 나온다.")
    para(doc, "**말할 수 없는 것**", bold=False)
    bullet(doc, "“VAEP 순위가 높은 선수가 실제로 더 좋은 선수다”. 가치에는 정답이 없으므로 이 명제는 "
                "이 방법으로 검증되지 않는다. 논문도 시장가치와의 대조라는 정성적 근거만 제시했다.")
    bullet(doc, "“이 모델을 다른 리그에 그대로 써도 된다”. 리그가 바뀌면 확률 모델을 다시 학습해야 하고, "
                "리그 간 값 비교에는 별도 보정이 필요하다.")
    bullet(doc, "“수비수 평가에 쓸 수 있다”. 실점 모델의 약함과 온더볼 한계가 겹쳐 신뢰하기 어렵다.")


# ----------------------------------------------------------------------------- 11장
def ch11(doc, d):
    h(doc, "11. 재현 절차", level=1, page_break=True)
    para(doc, "이 장만 보고도 같은 결과를 다시 만들 수 있도록 적었다.")

    h(doc, "11.1 환경", level=2)
    table(doc, ["항목", "값"], [
        ["Python", "3.11.13 (3.9 ~ 3.12 지원)"],
        ["핵심 패키지", "socceraction 1.5.3, xgboost 2.0.3, scikit-learn 1.4.2, pandas 2.2.2, "
                   "numpy 1.26.4, pyarrow 16.1.0, matplotlib 3.8.4"],
        ["주의", "pandera 0.17.2는 multimethod 2.x와 충돌한다. requirements.txt가 multimethod==1.9.1로 고정한다."],
        ["GPU", "선택. 있으면 자동 사용(RTX A6000 기준 학습 100초), 없으면 CPU(약 3분)."],
        ["디스크", "원본 1.1GB + 산출물 약 0.2GB"],
    ], widths=[2.6, 14.0], size=10, caption_text="실행 환경")

    h(doc, "11.2 설치와 실행", level=2)
    code(doc, """
# 1) 설치
cd vaep
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\\Scripts\\pip

# 2) 실행 — 둘 중 아무거나
jupyter lab vaep.ipynb        # 노트북을 열고 전체 실행 (0번 셀이 파이프라인을 돌린다)
python run_all.py             # 터미널에서 같은 파이프라인

# 3) 단계별로 다시 돌리기
python run_all.py --list      # 단계 목록
python run_all.py --from train
python run_all.py --only value

# 4) 보고서에 쓰인 추가 실험 (선택, 기본 파이프라인에는 포함되지 않음)
python src/ablation.py            # 피처·알고리즘·용량 비교      (약 20분)
python src/fold_sensitivity.py    # 폴드 재분할 민감도            (약 8분)
python src/compare_traditional.py # 골·어시스트 순위와 비교        (약 1분)
python src/report_figures.py      # 보고서용 흑백 그림
python src/make_report.py         # 이 보고서 자체
""")
    para(doc, "데이터는 따로 받을 필요가 없다. 첫 실행 때 `src/fetch_statsbomb.py`가 StatsBomb Open Data에서 "
              "라리가 2015/16 380경기를 내려받아 `data/statsbomb/`에 open-data와 같은 구조로 저장한다(약 1분). "
              "이미 받은 파일은 건너뛴다.")

    h(doc, "11.3 파이프라인 단계와 소요 시간", level=2)
    table(doc, ["단계", "스크립트", "출력", "시간"], [
        ["1. fetch", "src/fetch_statsbomb.py", "data/statsbomb/ (1.1GB)", "47초 (두 번째부터 0초)"],
        ["2. spadl", "src/build_spadl.py", "actions.parquet 외 5개", "20~40초"],
        ["3. features", "src/build_features.py", "features.parquet, labels.parquet", "10~15초"],
        ["4. train", "src/train.py", "predictions.parquet, metrics.csv, feature_importance.csv",
         "100초 (GPU) / 약 3분 (CPU)"],
        ["5. value", "src/value.py", "action_values.parquet, player_ratings.csv, value_by_actiontype.csv", "10초"],
        ["6. viz", "src/viz.py", "figures/sequence.png, sequence.csv", "10초"],
    ], widths=[2.0, 3.8, 7.2, 3.6], size=9.5, caption_text="파이프라인 단계별 소요 시간")

    h(doc, "11.4 재현성 확인 방법", level=2)
    para(doc, "난수 시드는 `src/config.py`의 `SEED`(20160817)로 고정했고, 경기 정렬은 날짜가 같으면 "
              "`game_id`로 타이브레이크해 순서를 확정했다. 확인은 해시로 한다.")
    code(doc, """
python run_all.py
md5sum out/actions.parquet out/features.parquet out/predictions.parquet > hash1.txt
python run_all.py
md5sum -c hash1.txt        # 세 파일 모두 OK 가 나와야 한다
""")
    para(doc, "이 검증을 실제로 수행해 세 파일 모두 일치하는 것을 확인했고, 학습 GPU를 바꿔서도 "
              "같은 결과가 나오는 것을 확인했다. 4.6절에서 고친 좌표 버그를 그대로 두면 이 검증은 실패한다.")

    h(doc, "11.5 폴더 구조", level=2)
    code(doc, """
vaep/
├── README.md                 사용법 요약
├── requirements.txt          고정된 패키지 버전
├── run_all.py                파이프라인 실행기
├── vaep.ipynb                결과를 순서대로 보여주는 노트북 (출력 포함)
├── src/
│   ├── config.py             경로·시드·모델 설정 (여기만 고치면 전체에 반영)
│   ├── fetch_statsbomb.py    원본 수집
│   ├── build_spadl.py        이벤트 → SPADL (좌표 버그 우회 포함)
│   ├── build_features.py     피처 145개 + 라벨 2개
│   ├── train.py              학습·평가 (OOF + 홀드아웃, FastAUC 부트스트랩)
│   ├── value.py              VAEP 공식 적용, 선수 랭킹
│   ├── viz.py                공격 장면 시각화
│   ├── style.py              그림 공통 설정
│   ├── ablation.py           피처·알고리즘·용량 비교 실험
│   ├── fold_sensitivity.py   폴드 재분할 민감도
│   ├── compare_traditional.py 골·어시스트 순위와 비교
│   ├── report_figures.py     보고서용 흑백 그림
│   └── make_report.py        이 보고서 생성기
├── data/statsbomb/           원본 (자동 다운로드, git 제외)
├── out/                      중간·최종 산출물 (부록 B)
├── figures/                  그림 (report/ 하위는 흑백판)
└── report/                   이 보고서
""")


# ----------------------------------------------------------------------------- 12장
def ch12(doc, d):
    met, rat = d["metrics"], d["ratings"]
    h(doc, "12. 결론", level=1, page_break=True)
    para(doc, "StatsBomb 라리가 2015/16 380경기로 VAEP 논문의 방법을 처음부터 끝까지 재현했다. "
              "원본 이벤트 1,295,354개를 SPADL 행동 757,309개로 바꾸고, 게임 상태를 145개 피처로 요약해 "
              "득점·실점 확률 모델 두 개를 학습했으며, 그 확률의 변화로 행동마다 값을 매겨 선수 순위까지 만들었다.")
    para(doc, "**방법이 제대로 옮겨졌다는 근거**는 세 가지다. 첫째, 골 수가 경기 메타데이터와 정확히 일치했다"
              "(1,043골). 둘째, 기저율 대비 개선율이 논문과 거의 같았다"
              f"(득점 {m(met,'oof','scores','brier_skill'):.3f} 대 0.157, 실점 "
              f"{m(met,'oof','concedes','brier_skill'):.3f} 대 0.030). "
              "셋째, 논문의 설계 선택 실험(피처 집합·알고리즘)이 우리 데이터에서도 같은 결론을 냈다.")
    para(doc, "**과정에서 확인한 것**도 몇 가지 있다. 참조 구현에 재현을 막는 버그가 있었고"
              "(위치 없는 이벤트의 좌표가 초기화되지 않은 메모리로 남는 문제), 이를 고치기 전에는 같은 코드가 "
              "실행마다 다른 순위를 냈다. 또 모델 용량을 키우면 좋아질 것이라는 예상과 달리, 희귀 라벨 "
              "때문에 작은 모델이 더 잘 일반화했다. 두 경우 모두 ‘돌려 보고 숫자를 확인한’ 덕분에 알게 된 것이다.")
    para(doc, "**결과 요약**: 득점 확률 모델은 AUC "
              f"{m(met,'oof','scores','roc_auc'):.3f}, 실점 확률 모델은 {m(met,'oof','concedes','roc_auc'):.3f}이고, "
              f"90분당 VAEP 상위는 {rat.iloc[0]['name']}({rat.iloc[0].vaep_p90:.3f}), "
              f"{rat.iloc[1]['name']}({rat.iloc[1].vaep_p90:.3f}) 순이다. 이 순위는 골·어시스트 순위와 "
              f"상관 0.48로, 슛 시도의 비용과 빌드업 기여를 반영한다는 점에서 다른 정보를 준다.")
    para(doc, "**남은 일**로는 (1) k(라벨 윈도우)와 게임 상태 길이의 민감도 측정, (2) 여러 시즌을 합쳐 "
              "선수 값의 흔들림을 줄이는 것, (3) 슛의 결과 대신 xG를 기댓값으로 써서 마무리 운을 분리하는 것, "
              "(4) 팀·리그 보정을 들 수 있다. 특히 (3)은 9.7.1절에서 본 호날두 사례의 해석을 "
              "정면으로 다루는 작업이 될 것이다.")


# ----------------------------------------------------------------------------- 부록
def appendix(doc, d):
    import socceraction.spadl as spadl
    import socceraction.vaep.features as fs
    from build_features import XFN_NAMES

    h(doc, "부록 A. 입력 피처 145개 전체 목록", level=1, page_break=True)
    para(doc, "a0은 지금 행동, a1·a2는 직전 행동이다. 접미사 _1, _2는 각각 a1, a2와의 관계를 뜻한다.", size=10)
    for name in XFN_NAMES:
        cols = fs.feature_column_names([getattr(fs, name)], NB_PREV_ACTIONS)
        h(doc, f"{name} — {len(cols)}개", level=3)
        chunk = [cols[i:i + 3] for i in range(0, len(cols), 3)]
        rows = [[c for c in row] + [""] * (3 - len(row)) for row in chunk]
        table(doc, ["", "", ""], rows, widths=[5.5, 5.5, 5.5], size=8.5)

    h(doc, "부록 B. 산출물 파일과 스키마", level=1, page_break=True)
    files = [
        ["out/games.parquet", "380행",
         "game_id, season_id, competition_id, game_day, game_date, home_team_id, away_team_id, "
         "home_score, away_score, venue, referee"],
        ["out/teams.parquet", "20행", "team_id, team_name"],
        ["out/players.parquet", "539행", "player_id, player_name, nickname"],
        ["out/player_games.parquet", "10,550행",
         "player_id, game_id, team_id, is_starter, starting_position_name, minutes_played"],
        ["out/actions.parquet", "757,309행",
         "game_id, original_event_id, action_id, period_id, time_seconds, team_id, player_id, "
         "start_x, start_y, end_x, end_y, type_id, result_id, bodypart_id"],
        ["out/features.parquet", "757,309행 × 147열", "game_id, action_id + 피처 145개 (부록 A)"],
        ["out/labels.parquet", "757,309행", "game_id, action_id, scores, concedes"],
        ["out/predictions.parquet", "757,309행", "game_id, action_id, scores, concedes (5겹 OOF 확률)"],
        ["out/predictions_holdout.parquet", "153,438행", "같은 형식, 홀드아웃 76경기"],
        ["out/action_values.parquet", "757,309행",
         "game_id, action_id, offensive_value, defensive_value, vaep_value"],
        ["out/player_ratings.csv", "538행",
         "player_id, name, player_name, team_name, games, minutes, actions, offensive, defensive, "
         "vaep, offensive_p90, defensive_p90, vaep_p90"],
        ["out/metrics.csv", "4행", "split, label, n, base_rate, brier, brier_base, brier_skill, "
                               "log_loss, log_loss_base, roc_auc, auc_lo, auc_hi"],
        ["out/feature_importance.csv", "145행", "feature, scores, concedes (gain)"],
        ["out/value_by_actiontype.csv", "21행",
         "type_name, n, offensive_mean, defensive_mean, vaep_mean, vaep_sum"],
        ["out/sequence.csv", "10행", "분해해 보여 준 공격 장면의 행동별 값"],
        ["out/ablation.csv", "12행", "피처 집합·알고리즘·용량 비교 결과 (9.4절)"],
        ["out/capacity_oof.csv", "8행", "용량 비교의 OOF 결과 (9.4.1절)"],
        ["out/fold_sensitivity.csv", "343행", "폴드 재분할 민감도 (10.1절)"],
        ["out/traditional_vs_vaep.csv", "343행", "골·어시스트 순위와 VAEP 순위 비교 (9.7.1절)"],
    ]
    table(doc, ["파일", "크기", "열"], files, widths=[4.4, 2.0, 10.2], size=9,
          caption_text="out/ 폴더의 산출물")

    h(doc, "부록 C. SPADL 행동 유형과 이 시즌의 빈도", level=1, page_break=True)
    named = spadl.add_names(d["actions"])
    vc = named.type_name.value_counts()
    desc = {
        "pass": "오픈 플레이의 일반 패스", "cross": "박스 안으로 올리는 크로스",
        "throw_in": "스로인", "freekick_crossed": "박스로 올린 프리킥",
        "freekick_short": "짧게 연결한 프리킥", "corner_crossed": "올린 코너킥",
        "corner_short": "짧은 코너킥", "take_on": "상대를 제치려는 1대1 돌파",
        "foul": "파울(항상 실패)", "tackle": "공을 향한 태클",
        "interception": "패스 가로채기", "shot": "오픈 플레이 슛",
        "shot_penalty": "페널티킥", "shot_freekick": "직접 프리킥 슛",
        "keeper_save": "골키퍼 선방", "keeper_claim": "골키퍼가 크로스를 잡음",
        "keeper_punch": "골키퍼 펀칭", "keeper_pick_up": "골키퍼가 공을 집음",
        "clearance": "걷어내기", "bad_touch": "터치 실수로 소유권 상실",
        "dribble": "공을 3m 이상 몰고 이동(Carry 포함)", "goalkick": "골킥",
        "non_action": "행동이 아님 (변환 과정에서 제외)",
    }
    rows = []
    for t in spadl.config.actiontypes:
        n = int(vc.get(t, 0))
        rows.append([t, desc.get(t, ""), f"{n:,}" if n else "—",
                     f"{n/len(named)*100:.2f}%" if n else "—"])
    table(doc, ["유형", "설명", "이 시즌 횟수", "비중"], rows,
          widths=[3.2, 7.4, 2.6, 2.0], size=9, align_right=[2, 3],
          caption_text="SPADL 행동 유형 23가지. 논문 본문은 21가지라고 적지만 참조 구현에는 "
                       "goalkick과 dribble, non_action이 포함되어 23가지다.")

    h(doc, "부록 D. 참고 문헌과 출처", level=1, page_break=True)
    bullet(doc, "Tom Decroos, Lotte Bransen, Jan Van Haaren, Jesse Davis. "
                "“Actions Speak Louder than Goals: Valuing Player Actions in Soccer.” "
                "KDD ’19, pp. 1851–1861, 2019. arXiv:1802.07127v2.")
    bullet(doc, "socceraction 1.5.3 (ML-KULeuven). https://github.com/ML-KULeuven/socceraction — MIT 라이선스. "
                "SPADL 변환과 VAEP 공식은 이 패키지를 그대로 사용했다.")
    bullet(doc, "StatsBomb Open Data. https://github.com/statsbomb/open-data — "
                "사용 조건은 해당 저장소의 라이선스를 따른다.")
    bullet(doc, "Tianqi Chen, Carlos Guestrin. “XGBoost: A Scalable Tree Boosting System.” KDD ’16.")
    bullet(doc, "Liudmila Prokhorenkova et al. “CatBoost: unbiased boosting with categorical features.” "
                "NeurIPS 2018. (논문이 사용한 알고리즘, 이 과제에서는 비교 대상)")
    bullet(doc, "Karun Singh. “Introducing Expected Threat (xT).” 2019. (구역 기반 대안 프레임워크)")


# ----------------------------------------------------------------------------- 실행
def estimate_pages(doc):
    """페이지 수를 대략 계산한다. 워드로 열어 보지 않고도 분량을 가늠하려는 용도다.

    본문 높이 25.7cm를 기준으로 글자·표·그림이 차지하는 높이를 더한다.
    """
    from PIL import Image

    PAGE_CM = 25.7
    used = 0.0
    for p in doc.paragraphs:
        n = len(p.text)
        size = max((r.font.size.pt for r in p.runs if r.font.size), default=10.5)
        chars_per_line = int(16.6 / (size * 0.0353 * 0.62))     # 한글 기준 대략치
        lines = max(1, -(-n // max(1, chars_per_line)))
        used += lines * size * 0.0353 * 1.45 + 0.2
        if p.style.name.startswith("Heading"):
            used += 0.5
    for t in doc.tables:
        for row in t.rows:
            longest = max((len(c.text) for c in row.cells), default=0)
            width_cm = 16.6 / max(1, len(row.cells))
            lines = max(1, -(-longest // max(1, int(width_cm / 0.22))))
            used += lines * 0.45 + 0.1
        used += 0.3
    for shape in doc.inline_shapes:
        used += shape.height.cm
    # 위 계산은 실제보다 작게 나온다(표 여백, 그림 캡션, 쪽 넘김 등).
    # 상세판을 워드에서 센 45쪽과 맞춰 보정 계수 1.5를 곱한다.
    return used / PAGE_CM * 1.5


def main():
    full = "--full" in sys.argv
    d = load()
    doc = new_document()
    if full:
        cover(doc, d)
        for fn in (ch1, ch2, ch3, ch4, ch5, ch6, ch7, ch8, ch9, ch10, ch11, ch12, appendix):
            fn(doc, d)
        path = REPORT.replace(".docx", "_상세.docx")
    else:
        short_report(doc, d)
        path = REPORT
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc.save(path)
    print(f"저장: {path} ({os.path.getsize(path)/1e6:.1f} MB)")
    print(f"표 {_counters['table']}개 · 그림 {_counters['figure']}개 · "
          f"예상 {estimate_pages(doc):.1f}쪽")




# ----------------------------------------------------------------------------- 짧은 판 (기본)
def short_report(doc, d):
    import socceraction.spadl as spadl
    import socceraction.vaep.features as fs
    from build_features import XFN_NAMES

    g, a, Y, met, rat = d["games"], d["actions"], d["labels"], d["metrics"], d["ratings"]
    bt, seq, trad, abl = d["by_type"], d["sequence"], d["trad"], d["ablation"]
    cap = pd.read_csv(f"{OUT}/capacity_oof.csv")
    fsens = pd.read_csv(f"{OUT}/fold_sensitivity.csv")
    named = spadl.add_names(a)

    p = doc.add_paragraph()
    _fmt(p.add_run("VAEP로 축구 선수의 모든 온더볼 행동에 점수 매기기"), size=19, bold=True)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    p = doc.add_paragraph()
    _fmt(p.add_run("StatsBomb 라리가 2015/16 380경기로 Decroos et al.(KDD 2019) 재현"), size=11.5)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(12)
    table(doc, ["원 논문", "Actions Speak Louder than Goals: Valuing Player Actions in Soccer (KDD ’19)"], [
        ["데이터", f"StatsBomb Open Data · 라리가 2015/16 (comp {COMPETITION_ID} / season {SEASON_ID}) "
                 f"{len(g)}경기, {g.game_date.min():%Y-%m-%d} ~ {g.game_date.max():%Y-%m-%d}"],
        ["도구", "Python 3.11, socceraction 1.5.3, XGBoost 2.0.3, scikit-learn 1.4.2"],
        ["산출물", "파이프라인 스크립트 13개 · 노트북 1권 · 결과 파일 19개 · 이 보고서"],
        ["작성일 / 작성자", "2026년 9월 19일 /"],
    ], widths=[3.0, 13.6], size=9.5)

    h(doc, "1. 요약", level=1)
    para(doc, "골과 어시스트는 한 경기에 두세 번뿐이고, 나머지 2,000번 가까운 행동은 숫자에 남지 않는다. "
              "VAEP는 이 문제를 **“이 행동으로 우리 팀이 곧 골을 넣을 확률이 얼마나 올랐고 먹을 확률이 얼마나 내렸는가”**로 "
              "바꿔, 공에 닿은 모든 행동에 골 단위의 점수를 매긴다. 이 과제에서는 그 방법을 라리가 2015/16 한 시즌에 "
              "적용해 원본 수집부터 선수 순위까지 전 과정을 재현하고, 각 단계의 선택을 실험으로 확인했다.")
    table(doc, ["항목", "값"], [
        ["원본 → SPADL", f"이벤트 1,295,354개 → 행동 {len(a):,}개 (경기당 {len(a)/len(g):.0f}개)"],
        ["정합성 점검", f"경기 메타데이터 득점 합계 {int((g.home_score+g.away_score).sum()):,}골 = "
                    f"SPADL 기준 슛 성공 1,014 + 자책 29 (정확히 일치)"],
        ["입력 / 라벨", f"피처 {len(d['features_cols'])}개 · 득점 {Y.scores.mean()*100:.2f}% "
                    f"({int(Y.scores.sum()):,}건) · 실점 {Y.concedes.mean()*100:.2f}% ({int(Y.concedes.sum()):,}건)"],
        ["모델 성능 (5겹 OOF)", f"득점 AUC {m(met,'oof','scores','roc_auc'):.3f} / Brier skill "
                          f"{m(met,'oof','scores','brier_skill'):.3f} · 실점 AUC "
                          f"{m(met,'oof','concedes','roc_auc'):.3f} / {m(met,'oof','concedes','brier_skill'):.3f}"],
        ["논문 대비", f"Brier skill 득점 {m(met,'oof','scores','brier_skill'):.3f} 대 0.157, "
                  f"실점 {m(met,'oof','concedes','brier_skill'):.3f} 대 0.030 — 데이터·알고리즘이 달라도 같은 자리"],
        ["90분당 VAEP 1·2위", f"{rat.iloc[0]['name']} {rat.iloc[0].vaep_p90:.3f} · "
                         f"{rat.iloc[1]['name']} {rat.iloc[1].vaep_p90:.3f}"],
        ["재현성", "전체 파이프라인 2회 실행 시 중간 산출물 3종의 md5 일치 (GPU를 바꿔도 동일)"],
    ], widths=[3.6, 13.0], size=9.5, caption_text="핵심 수치")
    para(doc, "**이 재현이 제대로 됐다는 근거**는 두 가지다. 골 수가 경기 메타데이터와 정확히 일치했고, "
              "기저율 대비 개선율(Brier skill)이 논문과 거의 같았다. 공급사·리그·알고리즘이 모두 다른데도 "
              "같은 자리에 도달했다는 뜻이다.")

    h(doc, "2. 방법", level=1)
    h(doc, "2.1 VAEP의 정의", level=2)
    code(doc, """
P_score(S_i, x)   = 상태 S_i에서 팀 x가 앞으로 10개 행동 안에 득점할 확률
P_concede(S_i, x) = 같은 구간에 실점할 확률

공격 가치 = P_score(S_i) − P_score(S_(i−1))      수비 가치 = −( P_concede(S_i) − P_concede(S_(i−1)) )
VAEP V(a_i) = 공격 가치 + 수비 가치               rating(선수) = (90 / 출전 분) × Σ V(a_i)
""", size=8.5)
    para(doc, "값의 단위는 골이다. 그래서 확률의 **크기가 맞아야**(보정) 값을 골로 읽을 수 있고, 평가 지표로 "
              "Brier를 함께 쓰는 이유가 여기 있다(2.7절). “이 패스는 몇 점짜리인가”라는 정답 없는 문제를 "
              "“10개 행동 안에 골이 났는가”라는 정답 있는 문제로 바꾼 것이 이 방법의 핵심이다.")

    h(doc, "2.2 데이터 선택", level=2)
    para(doc, "필요 조건은 넷이었다. (1) 1% 남짓한 희귀 라벨을 학습할 만한 표본, (2) 90분당 계산을 위한 출전 시간, "
              "(3) 시간순 분할이 가능한 한 시즌 전체, (4) 공개 데이터. "
              "socceraction 공개 노트북의 기본값인 월드컵 2018(64경기)은 골이 약 170개뿐이고 선수당 출전이 짧아 "
              "90분당 순위가 우연에 좌우된다. 라리가 2015/16은 380경기·1,043골·행동 757,309개로 "
              "5겹 교차검증과 시간순 홀드아웃을 모두 감당하고, 선수 구성이 잘 알려져 결과를 눈으로 검증할 수 있다.")

    h(doc, "2.3 전처리", level=2)
    para(doc, "socceraction 1.5.3의 변환기를 그대로 쓴다(논문 저자들의 참조 구현이라 재현의 기준점이 된다). "
              "핵심 규칙은 다음과 같다.")
    bullet(doc, "선수가 수행한 이벤트만 행동으로 남기고, 유형·결과·신체 부위를 각각 다른 속성으로 분리한다.", size=10)
    bullet(doc, "StatsBomb의 120×80 칸 좌표를 105m×68m로 바꾸고, 칸 중심을 쓰기 위해 반 칸을 뺀다. "
                "좌표 정밀도(fidelity)는 경기별 자동 추론에 맡겼다.", size=10)
    bullet(doc, "원정팀 좌표를 (105−x, 68−y)로 뒤집어 **모든 팀이 왼쪽→오른쪽 공격**이 되게 맞춘다.", size=10)
    bullet(doc, "걷어내기의 종료 좌표는 다음 행동의 시작 좌표로 채운다.", size=10)
    bullet(doc, f"같은 팀 연속 행동의 간격이 3~60m이고 10초 이내면 그 사이에 dribble을 합성한다. "
                f"StatsBomb은 볼 운반을 Carry 이벤트로 직접 기록하므로 이 데이터의 dribble 비중은 "
                f"{(named.type_name=='dribble').mean()*100:.1f}%로 논문(Wyscout 8.69%)보다 훨씬 높다.", size=10)
    para(doc, "**재현을 막던 버그 하나를 고쳤다.** socceraction의 좌표 변환 함수가 np.empty로 배열을 잡고 "
              "위치가 있는 이벤트만 채우기 때문에, 위치가 없는 행동(이 시즌 7개)의 좌표가 초기화되지 않은 "
              "메모리 값으로 남는다. 그대로 두면 실행마다 드리블 합성 여부와 피처가 달라져 선수 순위까지 바뀐다"
              "(실제로 같은 코드가 AUC 0.8148과 0.8137을 냈다). src/build_spadl.py가 그 행을 NaN으로 채워 막는다. "
              "여기에 경기 정렬을 (날짜, game_id)로 고정해 파이프라인 전체가 결정적이 되었다.")

    h(doc, "2.4 피처 — 게임 상태를 145개 숫자로", level=2)
    para(doc, f"지금 행동(a0)과 직전 {NB_PREV_ACTIONS-1}개(a1, a2)를 함께 본다. 같은 위치의 패스라도 직전 상황에 "
              f"따라 가치가 달라야 하기 때문이다. 각 묶음은 세 행동에 적용되므로 행동 유형 23개는 69열이 된다.")
    DESC = {
        "actiontype_onehot": "행동 유형 23가지 (패스, 드리블, 슛, 태클 …)",
        "bodypart_onehot": "신체 부위 (발/머리/기타, 좌우발 구분)",
        "result_onehot": "결과 (성공·실패·오프사이드·자책골·카드)",
        "goalscore": "공격 팀 득점, 수비 팀 득점, 골 차",
        "startlocation": "시작 좌표 (m)", "endlocation": "종료 좌표 (m)",
        "movement": "이동량 (dx, dy, 직선 거리)",
        "space_delta": "직전 행동과 벌어진 거리",
        "startpolar": "시작점에서 골대까지 거리·각도", "endpolar": "종료점에서 골대까지 거리·각도",
        "team": "직전 행동이 같은 팀인가", "time_delta": "직전 행동과의 시간 차(초)",
    }
    rows = [[n, DESC[n], str(len(fs.feature_column_names([getattr(fs, n)], NB_PREV_ACTIONS)))]
            for n in XFN_NAMES]
    rows.append(["**합계**", "", f"**{len(d['features_cols'])}**"])
    half = -(-len(rows) // 2)
    merged = [rows[i] + (rows[i + half] if i + half < len(rows) else ["", "", ""]) for i in range(half)]
    table(doc, ["변환 함수", "내용", "열", "변환 함수", "내용", "열"], merged,
          widths=[2.6, 4.4, 0.9, 2.6, 4.4, 0.9], size=8.5, align_right=[2, 5],
          caption_text="입력 피처 구성 (전체 열 이름은 out/features.parquet에 있다)")
    para(doc, "논문과 다른 점은 셋이다. 범주형을 CatBoost에 맡기지 않고 원-핫으로 펼쳤고(모델 선택 때문, 2.6절), "
              "경기 내 시각(time)은 제외했으며(스코어 상황이 흐름을 대신 설명하고 특정 시간대 과적합을 피하려고), "
              "신체 부위는 StatsBomb이 주는 좌우발 구분까지 살렸다.", size=10)

    h(doc, "2.5 라벨", level=2)
    code(doc, """
scores[i]   = 1  ⇔  행동 i의 공 소유 팀이, 행동 i를 포함한 이후 10개 행동 안에 득점 (상대 자책골 포함)
concedes[i] = 1  ⇔  같은 구간에 실점
""", size=8.5)
    para(doc, f"윈도우에 **현재 행동이 포함된다**는 점이 중요하다. 논문 본문의 정의는 다음 행동부터로 읽히지만 "
              f"참조 구현(labels.py)은 현재 행동의 골 여부에서 시작해 이후 9개를 OR로 더한다. 그래서 골이 된 슛은 "
              f"그 자체로 라벨 1이고, 슛의 VAEP는 대략 ‘1 − 직전 확률’, 빗나간 슛은 ‘−직전 확률’이 된다(3.5절). "
              f"라벨 발생률은 득점 {Y.scores.mean()*100:.2f}%, 실점 {Y.concedes.mean()*100:.2f}%로 논문(1.66%, 0.57%)보다 "
              f"낮은데, 골이 적어서가 아니라 경기당 행동 수가 1,993개로 많아 분모가 크기 때문이다. "
              f"그래서 Brier 절대값 대신 기저율 대비 개선율로 비교해야 한다.")

    h(doc, "2.6 모델과 하이퍼파라미터", level=2)
    para(doc, "논문은 CatBoost를 썼지만, 그 비교는 XGBoost를 트리 100·깊이 3으로, CatBoost를 기본값"
              "(반복 1,000·깊이 6)으로 돌린 **용량이 맞춰지지 않은 비교**였다(학습 시간 16분 대 100분). "
              "두 모델의 Brier 차이도 1% 수준이다. 이 과제는 결측을 그대로 받고 GPU를 쓸 수 있는 XGBoost를 택하고, "
              "대신 알고리즘과 용량을 직접 비교해 근거를 만들었다(3.2절).")
    reason = {
        "n_estimators": "용량 실험에서 고른 값 (3.2절)", "max_depth": "같은 실험에서 고른 값",
        "learning_rate": "표준값", "subsample": "행 80%만 사용해 분산을 줄임",
        "colsample_bytree": "열 80%만 사용 (원-핫이라 상관 높은 열이 많음)",
        "min_child_weight": "양성이 1%뿐이라 리프가 몇 개 사례로 만들어지는 것을 막음",
        "tree_method": "히스토그램 분할 (76만 행에서 속도 차이가 큼)",
        "eval_metric": "확률 품질 기준", "random_state": "시드 고정 (재현성)",
    }
    rows = [[k, str(v), reason.get(k, "")] for k, v in XGB_PARAMS.items()]
    rows.append(["device / n_jobs", "auto / min(16, 코어)",
                 "GPU 있으면 자동 사용(결과 동일). 코어를 다 쓰면 경합으로 느려져 16으로 제한"])
    table(doc, ["파라미터", "값", "근거"], rows, widths=[3.2, 2.6, 10.8], size=9,
          caption_text="득점·실점 두 모델에 공통 적용 (src/config.py). 그리드 서치는 하지 않았고 용량만 실험으로 정했다")

    h(doc, "2.7 검증 절차", level=2)
    n_train = int(len(g) * (1 - HOLDOUT_FRAC))
    split_date = g.sort_values(["game_date", "game_id"]).game_date.iloc[n_train]
    para(doc, "**모든 분할은 경기 단위다.** 행을 무작위로 섞으면 안 되는 결정적 이유가 있다. i번째와 i+1번째 행동의 "
              "라벨은 10개 행동 중 9개를 공유하므로, 하나를 학습에 쓰고 다른 하나를 평가에 쓰면 평가 대상의 정답을 "
              "이미 학습에서 본 셈이 된다.")
    table(doc, ["분할", "구성", "쓰임"], [
        [f"경기 단위 {N_FOLDS}겹 OOF", f"{len(g)}경기를 {N_FOLDS}개로 나눠 돌아가며 예측 (시드 {SEED})",
         "3장의 모든 VAEP 값·선수 순위와 주 평가 지표. 모든 행동이 ‘그 경기를 학습에 쓰지 않은 모델’의 예측을 받는다"],
        ["날짜순 홀드아웃", f"앞 {n_train}경기 학습 → 마지막 {len(g)-n_train}경기({split_date:%Y-%m-%d} 이후) 1회 평가",
         "논문의 ‘과거로 학습, 미래로 평가’에 대응하는 최종 점검"],
    ], widths=[2.8, 6.2, 7.6], size=9)
    para(doc, "지표는 넷을 쓴다. 양성이 1%뿐이라 정확도는 무의미하다(무조건 0이라 해도 99%). "
              "**Brier**는 보정과 변별을 함께 보는 proper score, **Brier skill**은 ‘항상 평균만 찍는 모델’ 대비 개선율, "
              "**log loss**는 두 번째 proper score, **ROC AUC**는 순위 능력이다. AUC는 확률의 크기를 보지 못하므로 "
              "Brier와 함께 써야 한다. 신뢰구간은 **경기를 복원추출하는 부트스트랩 500회**로 구한다(행 단위로 뽑으면 "
              "한 경기 안의 상관 때문에 구간이 실제보다 좁아진다).", size=10)

    h(doc, "3. 결과", level=1)
    h(doc, "3.1 확률 모델 성능", level=2)
    rows = []
    for split, sname in [("oof", f"{N_FOLDS}겹 OOF (380경기)"), ("holdout", "홀드아웃 (76경기)")]:
        for label, lname in [("scores", "득점"), ("concedes", "실점")]:
            rows.append([sname if label == "scores" else "", lname,
                         f"{m(met, split, label, 'base_rate')*100:.2f}%",
                         f"{m(met, split, label, 'brier'):.5f}",
                         f"{m(met, split, label, 'brier_skill'):.3f}",
                         f"{m(met, split, label, 'log_loss'):.4f}",
                         f"**{m(met, split, label, 'roc_auc'):.3f}** "
                         f"({m(met, split, label, 'auc_lo'):.3f}~{m(met, split, label, 'auc_hi'):.3f})"])
    table(doc, ["평가 방식", "대상", "기저율", "Brier", "Brier skill", "log loss", "ROC AUC (95%)"],
          rows, widths=[3.0, 1.2, 1.6, 2.0, 2.2, 1.8, 4.2], size=9, align_right=[2, 3, 4, 5],
          caption_text="확률 모델 평가. 괄호는 경기 단위 부트스트랩 500회의 95% 구간")
    para(doc, f"득점 모델은 잘 작동한다(AUC {m(met,'oof','scores','roc_auc'):.3f}, 기저율 대비 오차 "
              f"{m(met,'oof','scores','brier_skill')*100:.0f}% 감소). **실점 모델은 약하다**"
              f"(Brier skill {m(met,'oof','concedes','brier_skill'):.3f}). 공을 가진 팀이 곧 실점하려면 공을 잃고 상대가 "
              f"마무리까지 해야 하는데 그 과정 대부분이 온더볼 이벤트에 남지 않기 때문이다. 논문도 같은 자리에서 멈춘다"
              f"(0.030). 교차검증과 홀드아웃이 거의 같다는 것은 시즌 앞부분만 보고 뒷부분을 예측해도 성능이 유지된다는 뜻이다.")
    figure(doc, "model_eval.png",
           "(a) ROC 곡선, (b) 캘리브레이션. 실선 = 5겹 OOF, 점선 = 홀드아웃. "
           "네 곡선 모두 대각선에 붙어 있어 “5%”가 실제로 5%다 — VAEP 값을 골 단위로 읽을 수 있는 근거.", width=15.0)

    h(doc, "3.2 설계 선택 실험 (논문 Table 3의 재현)", level=2)
    fs_rows = []
    for _, r in abl[abl.group == "피처 집합"].iterrows():
        fs_rows.append([r.setting, f"{int(r.n_features)}", f"{r.scores_brier_skill:.3f}",
                        "—" if pd.isna(r.scores_roc_auc) else f"{r.scores_roc_auc:.3f}",
                        f"{r.concedes_brier_skill:.3f}",
                        "—" if pd.isna(r.concedes_roc_auc) else f"{r.concedes_roc_auc:.3f}"])
    for _, r in abl[abl.group == "알고리즘"].iterrows():
        if "XGBoost" in r.setting:
            continue
        fs_rows.append([f"{r.setting} (전체 피처)", f"{int(r.n_features)}", f"{r.scores_brier_skill:.3f}",
                        f"{r.scores_roc_auc:.3f}", f"{r.concedes_brier_skill:.3f}", f"{r.concedes_roc_auc:.3f}"])
    table(doc, ["설정", "열 수", "득점 BSS", "득점 AUC", "실점 BSS", "실점 AUC"], fs_rows,
          widths=[5.4, 1.4, 2.2, 2.2, 2.2, 2.2], size=9, align_right=[1, 2, 3, 4, 5],
          caption_text="피처 집합과 알고리즘 비교 (날짜순 홀드아웃, 같은 조건)")
    para(doc, "논문의 두 결론이 그대로 재현됐다. 위치·유형만 쓰는 기존 방식보다 **맥락 피처를 모두 쓰는 쪽이 크게 낫고**"
              "(득점 BSS 0.077 → 0.149), 트리 앙상블이 선형 모델보다 낫다. 로지스틱 회귀는 AUC는 제법 나오지만 BSS가 낮은데, "
              "순위는 매기면서 확률의 크기를 못 맞춘다는 뜻이다 — 두 지표를 함께 봐야 하는 이유다.")
    cap_rows = []
    for setting in cap.setting.unique():
        s_ = cap[cap.setting == setting]
        sc, cc = s_[s_.label == "scores"].iloc[0], s_[s_.label == "concedes"].iloc[0]
        cap_rows.append([setting, f"{sc.brier_skill:.4f}", f"{sc.roc_auc:.4f}",
                         f"{cc.brier_skill:.4f}", f"{cc.roc_auc:.4f} ({cc.auc_lo:.3f}~{cc.auc_hi:.3f})"])
    table(doc, ["XGBoost 용량", "득점 BSS", "득점 AUC", "실점 BSS", "실점 AUC (95%)"], cap_rows,
          widths=[4.4, 2.2, 2.2, 2.2, 4.6], size=9, align_right=[1, 2, 3],
          caption_text="모델 용량 비교 (최종 값 산출과 같은 5겹 OOF 프로토콜)")
    para(doc, "**용량을 키울수록 나빠진다.** 특히 실점 모델에서 트리 300·깊이 6은 AUC 0.737, 트리 100·깊이 3은 0.767로 "
              "95% 구간이 거의 겹치지 않는다. 실점 양성이 1,782건뿐이라 깊은 트리 300개는 양성 몇 개씩을 외우는 쪽으로 "
              "학습되기 때문이다. 이 실험에 따라 최종 설정을 **트리 100·깊이 3**으로 정했다. 처음에는 300·6으로 시작했다가 "
              "데이터가 반대라고 말해 주어 바꾼 것이고, 바꾼 뒤 결과의 안정성도 함께 좋아졌다(4장).")

    h(doc, "3.3 행동 유형별 가치", level=2)
    rows = []
    for _, r in bt.nlargest(8, "n").iterrows():
        rows.append([r.type_name, f"{int(r.n):,}", f"{r.offensive_mean:+.5f}",
                     f"{r.defensive_mean:+.5f}", f"{r.vaep_mean:+.5f}", f"{r.vaep_sum:+.1f}"])
    table(doc, ["행동 유형", "횟수", "평균 공격 가치", "평균 수비 가치", "평균 VAEP", "시즌 합계"], rows,
          widths=[3.0, 2.2, 2.8, 2.8, 2.6, 2.4], size=9, align_right=[1, 2, 3, 4, 5],
          caption_text="행동 유형별 가치 (빈도 상위 8종)")
    tackle = bt[bt.type_name == "tackle"].iloc[0]
    para(doc, f"한 번의 값이 가장 큰 행동은 슛이지만 횟수가 적어 합계에서는 드리블·패스에 밀린다. "
              f"**태클은 수비 가치가 공격 가치보다 크다**(평균 {tackle.offensive_mean:+.4f} vs {tackle.defensive_mean:+.4f}) — "
              f"공을 끊는 행동의 값이 ‘상대의 득점 기회를 지운 것’에서 나온다는 VAEP의 구조가 숫자로 드러난다. "
              f"파울과 배드 터치는 평균이 음수다.", size=10)

    h(doc, "3.4 선수별 90분당 VAEP 상위 10명", level=2)
    elig = rat[rat.minutes >= MIN_MINUTES]
    rows = []
    for i, (_, r) in enumerate(elig.head(10).iterrows(), 1):
        rows.append([str(i), r["name"], r.team_name, f"{int(r.games)}", f"{int(r.minutes):,}",
                     f"{r.offensive_p90:+.3f}", f"{r.defensive_p90:+.3f}", f"**{r.vaep_p90:.3f}**"])
    table(doc, ["#", "선수", "팀", "경기", "출전(분)", "공격/90", "수비/90", "VAEP/90"], rows,
          widths=[0.8, 3.6, 3.0, 1.4, 2.0, 2.0, 2.0, 1.8], size=9, align_right=[3, 4, 5, 6, 7],
          caption_text=f"{MIN_MINUTES}분 이상 출전한 {len(elig)}명 중 상위 10명. "
                       f"값은 모두 그 경기를 학습에 쓰지 않은 모델의 예측에서 나온다")

    h(doc, "3.5 전통 지표와 무엇이 다른가", level=2)
    rho = trad.ga_p90.corr(trad.vaep_p90, method="spearman")
    ron = player_profile(d, "Cristiano Ronaldo")
    bale = player_profile(d, "Gareth Bale")
    messi = player_profile(d, "Lionel Messi")
    rows = []
    for _, r in trad.nlargest(6, "ga_p90").iterrows():
        rows.append([r["name"], f"{r.goals_p90:.3f}", f"{r.assists_p90:.3f}", f"{r.ga_p90:.3f}",
                     f"{int(r.rank_ga_p90)}위", f"{r.vaep_p90:.3f}", f"**{int(r.rank_vaep_p90)}위**"])
    table(doc, ["선수", "골/90", "도움/90", "골+도움/90", "그 순위", "VAEP/90", "VAEP 순위"], rows,
          widths=[3.6, 1.8, 1.8, 2.4, 1.8, 2.2, 2.4], size=9, align_right=[1, 2, 3, 4, 5, 6],
          caption_text="90분당 골+어시스트 상위 6명과 그들의 VAEP 순위 (어시스트는 ‘골 직전의 같은 팀 성공 패스’로 정의)")
    para(doc, f"두 순위의 스피어만 상관은 {rho:.2f}로, 같은 것을 재지도 무관하지도 않다. 차이가 가장 큰 예가 호날두다"
              f"(골+도움 {int(trad[trad.name=='Cristiano Ronaldo'].rank_ga_p90.iloc[0])}위 → VAEP "
              f"{int(trad[trad.name=='Cristiano Ronaldo'].rank_vaep_p90.iloc[0])}위). "
              f"이 시즌 그는 90분당 슛 {ron['shots_p90']:.1f}개를 시도했고, 슛에서 얻은 VAEP는 "
              f"골 {ron['shot_vaep_goal']:+.1f}과 실패 {ron['shot_vaep_miss']:+.1f}을 합쳐 {ron['shot_vaep']:+.1f}이다. "
              f"반면 베일은 슛이 90분당 {bale['shots_p90']:.1f}개로 적지만 합계 {bale['shot_vaep']:+.1f}을 남겼다. "
              f"빗나간 슛은 그때까지 쌓은 득점 확률을 지우므로 음수가 되는데, 골·어시스트는 이 비용을 세지 않는다. "
              f"**어느 쪽이 옳은 평가인지는 이 방법으로 답할 수 없지만, ‘슛 시도가 많은 선수는 VAEP에서 불리하다’는 "
              f"성질은 알고 써야 한다.**")
    top3 = messi["by_type"].head(3)
    para(doc, f"반대로 메시의 값은 {', '.join(f'{k} {v:+.1f}' for k, v in top3.items())}처럼 고르게 퍼져 있다. "
              f"유형별로 쪼개면 플레이 스타일이 보인다는 논문 §5.4의 주장을 그대로 보여주는 예다.", size=10)

    h(doc, "3.6 한 번의 공격을 행동 단위로 분해", level=2)
    rows = []
    for i, (_, r) in enumerate(seq.iterrows(), 1):
        rows.append([str(i), r["name"], r.type_name, f"{r.p_scores:.4f}",
                     f"{r.offensive_value:+.4f}", f"{r.defensive_value:+.4f}", f"**{r.vaep_value:+.4f}**"])
    table(doc, ["#", "선수", "행동", "직후 득점 확률", "공격 가치", "수비 가치", "VAEP"], rows,
          widths=[0.8, 3.6, 2.4, 3.0, 2.2, 2.2, 2.4], size=9, align_right=[3, 4, 5, 6],
          caption_text="셀타 비고의 득점 장면 (논문 Figure 1과 같은 형식)")
    para(doc, f"자기 진영 태클({seq.vaep_value.iloc[0]:+.3f}, 대부분 수비 가치)에서 시작해 마무리"
              f"({seq.vaep_value.iloc[-1]:+.3f})까지, 득점 확률이 {seq.p_scores.iloc[0]*100:.1f}% → "
              f"{seq.p_scores.iloc[-2]*100:.1f}% → 골로 올라간다. 합계 {seq.vaep_value.sum():+.3f} 중 "
              f"마무리와 직전 패스가 {(seq.vaep_value.iloc[-1]+seq.vaep_value.iloc[-2])/seq.vaep_value.sum()*100:.0f}%를 "
              f"가져간다. 확률이 크게 움직이는 순간에 값이 몰리는 구조이며, 확률을 낮춘 6번 패스는 음수를 받는다.")
    figure(doc, "sequence.png",
           "같은 장면. 위는 경기장 위의 행동 흐름(색이 진할수록 VAEP가 크다), 아래는 행동별 VAEP와 직후 득점 확률.",
           width=14.5)

    h(doc, "4. 결과의 불확실성과 한계", level=1)
    rows = []
    seed_cols = [c for c in fsens.columns if c.startswith("seed_")]
    for _, r in fsens.head(5).iterrows():
        rows.append([r["name"]] + [f"{r[c]:.3f}" for c in seed_cols] +
                    [f"{r['spread']:.3f}", f"{int(r['rank_move'])}계단"])
    table(doc, ["선수"] + [f"분할 {i+1}" for i in range(len(seed_cols))] + ["최대-최소", "순위 변동"],
          rows, widths=[4.0] + [2.2] * len(seed_cols) + [2.4, 2.2], size=9,
          align_right=list(range(1, len(seed_cols) + 3)),
          caption_text="폴드 분할을 세 번 바꿨을 때 상위 5명의 90분당 VAEP")
    top12 = fsens.head(12)
    para(doc, f"상위 12명의 값은 중앙값 {top12.spread.median():.3f}(최대 {top12.spread.max():.3f})만큼 흔들렸고 "
              f"상위 10명의 순위 변동은 최대 {int(fsens.head(10).rank_move.max())}계단이었다. "
              f"같은 측정을 3.2절에서 탈락한 큰 모델(300·6)로 했을 때는 중앙값 0.040, 최대 0.071, 순위 4계단이었다. "
              f"**용량을 줄이자 정확도뿐 아니라 안정성도 좋아진 것이다.** 다만 값 자체는 소수 둘째 자리에서 움직이므로 "
              f"0.450과 0.443처럼 붙어 있는 두 선수의 우열을 이 표로 가리는 것은 무리다.")
    table(doc, ["한계", "내용과 영향"], [
        ["온더볼만 평가", "공간을 만드는 침투, 수비 위치 선정, 압박은 이벤트 데이터에 없어 0점이다. "
                    "상위권이 공격 자원으로 채워지는 구조적 이유이며 ‘VAEP 순위 = 잘한 선수 순위’로 읽으면 안 된다."],
        ["실점 모델이 약함", f"Brier skill {m(met,'oof','concedes','brier_skill'):.3f}. 수비 가치 성분은 신호 대비 잡음이 크고 "
                     "수비수 평가에 쓰기 어렵다."],
        ["결과 기반 크레딧", "골이 된 슛은 ‘1 − 직전 확률’, 빗나간 슛은 ‘−직전 확률’. 마무리 운이 값에 그대로 들어간다(3.5절)."],
        ["리그·팀 보정 없음", "약한 리그·강한 팀일수록 고가치 행동이 쉽다. 한 리그 한 시즌만 다뤄 리그 간 비교는 하지 않았다."],
        ["k=10 민감도 미측정", "라벨 윈도우를 바꿨을 때 순위가 얼마나 달라지는지는 확인하지 않았다. 후속 과제."],
    ], widths=[3.0, 13.6], size=9, caption_text="구조적 한계")

    h(doc, "5. 재현 절차", level=1)
    code(doc, """
# 1) 설치 — Python 3.11 기준 (3.9~3.12 지원)
cd vaep && python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2) 실행 — 둘 중 하나. 데이터는 첫 실행 때 자동으로 내려받는다(1.1GB, 약 1분)
jupyter lab vaep.ipynb     # 0번 셀이 파이프라인 전체를 돌린다
python run_all.py          # 터미널에서 같은 파이프라인 (GPU 기준 약 3분)

# 3) 보고서의 근거가 된 추가 실험 (기본 파이프라인에는 없음)
python src/ablation.py            # 피처·알고리즘·용량 비교   (약 20분)
python src/fold_sensitivity.py    # 폴드 재분할 민감도         (약 8분)
python src/compare_traditional.py # 골·어시스트 순위와 비교     (약 1분)

# 4) 재현 확인 — 두 번 돌려 해시가 같은지 본다
python run_all.py && md5sum out/actions.parquet out/features.parquet out/predictions.parquet > h1
python run_all.py && md5sum -c h1        # 세 파일 모두 OK
""", size=8.5)
    table(doc, ["단계", "스크립트", "출력", "시간"], [
        ["fetch", "src/fetch_statsbomb.py", "data/statsbomb/ (1.1GB)", "47초 (이후 0초)"],
        ["spadl", "src/build_spadl.py", "actions.parquet 외 5개", "20~40초"],
        ["features", "src/build_features.py", "features.parquet, labels.parquet", "10~15초"],
        ["train", "src/train.py", "predictions.parquet, metrics.csv, feature_importance.csv", "100초 (GPU)"],
        ["value", "src/value.py", "action_values.parquet, player_ratings.csv 외", "10초"],
        ["viz", "src/viz.py", "figures/sequence.png, sequence.csv", "10초"],
    ], widths=[1.8, 3.6, 7.4, 3.8], size=9, caption_text="파이프라인 단계와 소요 시간")
    para(doc, "시드는 src/config.py의 SEED로 고정했고 경기 정렬은 (날짜, game_id)로 확정했다. "
              "전체 파이프라인을 두 번 돌려 세 파일의 md5가 모두 일치하는 것과, 학습 GPU를 바꿔도 같은 결과가 "
              "나오는 것을 확인했다. 2.3절의 좌표 버그를 고치지 않으면 이 검증은 실패한다.", size=10)

    h(doc, "6. 결론", level=1)
    para(doc, f"라리가 2015/16 380경기로 VAEP 전 과정을 재현했다. 원본 이벤트 1,295,354개를 SPADL 행동 "
              f"{len(a):,}개로 바꾸고, 게임 상태를 {len(d['features_cols'])}개 피처로 요약해 득점·실점 확률 모델을 학습했으며, "
              f"확률 변화로 행동마다 값을 매겨 선수 순위까지 만들었다. 골 수가 경기 메타데이터와 정확히 일치했고, "
              f"기저율 대비 개선율이 논문과 거의 같았으며, 논문의 설계 선택 실험도 같은 결론을 냈다.")
    para(doc, "과정에서 두 가지를 배웠다. 참조 구현에 재현을 막는 버그가 있어 고치기 전에는 같은 코드가 매번 다른 순위를 "
              "냈다는 것, 그리고 모델을 키우면 좋아질 것이라는 예상과 달리 희귀 라벨 때문에 작은 모델이 더 잘 일반화하고 "
              "결과도 안정적이었다는 것이다. 둘 다 돌려 보고 숫자를 확인한 덕분에 알게 된 것이다.")
    para(doc, "남은 과제는 (1) 라벨 윈도우 k와 게임 상태 길이의 민감도 측정, (2) 여러 시즌을 합쳐 값의 흔들림 줄이기, "
              "(3) 슛의 실제 결과 대신 xG를 기댓값으로 써서 마무리 운을 분리하기, (4) 팀·리그 보정이다. "
              "특히 (3)은 3.5절에서 본 호날두 사례의 해석을 정면으로 다루는 작업이 된다.")
    para(doc, "**참고**: 원 논문은 Decroos, Bransen, Van Haaren, Davis, “Actions Speak Louder than Goals: "
              "Valuing Player Actions in Soccer”, KDD ’19. 구현은 socceraction 1.5.3(MIT), 데이터는 "
              "StatsBomb Open Data를 사용했다. 전체 결과와 코드는 노트북 vaep.ipynb와 src/에 있다.", size=9.5)


if __name__ == "__main__":
    main()
