"""그림 공통 설정: 한글 폰트와 색."""
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

# 색은 역할별로 여기서만 정의한다
INK, INK2, MUTED, GRID, BASE, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#d64545"
PITCH_LINE, PITCH_FACE = "#c3c2b7", "#fcfcfb"


def korean_font():
    """시스템에 있는 한글 폰트를 찾는다. 없으면 koreanize-matplotlib의 나눔고딕을 등록한다."""
    have = {f.name for f in fm.fontManager.ttflist}
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "NanumBarunGothic"):
        if name in have:
            return name
    try:
        import koreanize_matplotlib  # noqa: F401  (import만으로 폰트를 등록한다)

        return plt.rcParams["font.family"][0]
    except Exception:
        return "sans-serif"


def _warmup():
    """폰트 캐시를 미리 채운다.

    주피터 커널에서 첫 번째 그림만 PNG 없이 `<Figure ...>` 글자만 남는 일이 있다.
    첫 렌더링에서 폰트 캐시를 만드는 사이 인라인 백엔드의 PNG 변환이 조용히 실패하기 때문이다.
    여기서 버리는 그림을 한 장 미리 그려 두면 이후 모든 그림이 정상으로 뜬다.
    """
    import io

    fig = plt.figure(figsize=(1, 1))
    fig.text(0.5, 0.5, "한글 ABC 123")
    try:
        fig.savefig(io.BytesIO(), format="png")
    except Exception:
        pass
    finally:
        plt.close(fig)


def use():
    """노트북과 스크립트가 같은 그림 스타일을 쓰도록 rcParams를 맞춘다."""
    plt.rcParams.update({
        "font.family": korean_font(),
        "axes.unicode_minus": False,
        "font.size": 10,
        "figure.dpi": 110,
        "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
        "axes.edgecolor": BASE, "axes.labelcolor": INK2,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "text.color": INK, "axes.titlecolor": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "legend.frameon": False,
    })
    _warmup()
