"""프로젝트 전체가 공유하는 경로와 상수."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SB_DIR = os.path.join(DATA, "statsbomb")          # StatsBomb open-data 원본 (레이아웃 그대로)
OUT = os.path.join(ROOT, "out")                   # 중간 산출물 (parquet/csv)
FIG = os.path.join(ROOT, "figures")               # 그림

# 대상 대회: StatsBomb open data의 라리가 2015/16 (380경기)
COMPETITION_ID = 11
SEASON_ID = 27
COMPETITION_NAME = "La Liga"
SEASON_NAME = "2015/2016"

SEED = 20160817          # 라리가 2015/16 개막일
N_FOLDS = 5              # 경기 단위 교차검증 폴드 수
HOLDOUT_FRAC = 0.2       # 날짜순 뒤쪽 몇 %를 최종 점검용으로 뺄지
NB_PREV_ACTIONS = 3      # 게임 상태 = 현재 행동 + 직전 2개 (VAEP 논문과 동일)
MIN_MINUTES = 900        # 선수 랭킹에 넣을 최소 출전 시간 (10경기)

# 득점/실점 확률 모델 (두 모델 모두 같은 설정).
# 트리 수와 깊이는 src/ablation.py의 용량 실험에서 고른 값이다. 50/3, 100/3, 200/4, 300/6을
# 같은 5겹 OOF로 비교했더니 100/3이 가장 균형 있게 좋았다. 양성이 1%뿐이라 큰 모델은 과적합한다.
XGB_PARAMS = dict(
    n_estimators=100,
    max_depth=3,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=10,
    tree_method="hist",
    eval_metric="logloss",
    random_state=SEED,
)

for _d in (DATA, SB_DIR, OUT, FIG):
    os.makedirs(_d, exist_ok=True)
