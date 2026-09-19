"""VAEP 파이프라인을 순서대로 한 번에 실행한다.

    python run_all.py                 전체 (1~6단계)
    python run_all.py --from train    4단계부터 이어서
    python run_all.py --only value    5단계만
    python run_all.py --list          단계 목록
    python run_all.py -q              각 단계의 마지막 줄만 표시

실패하면 그 단계에서 멈추고 에러 끝부분을 보여준다.
고친 뒤 `--from <단계>`로 이어서 돌리면 된다.
"""
import argparse
import collections
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))

PIPELINE = [
    ("fetch",    "src/fetch_statsbomb.py", "StatsBomb 라리가 2015/16 다운로드 (있으면 건너뜀)"),
    ("spadl",    "src/build_spadl.py",     "원본 이벤트 -> SPADL 행동 (out/actions.parquet)"),
    ("features", "src/build_features.py",  "피처·라벨 (out/features.parquet, labels.parquet)"),
    ("train",    "src/train.py",           "득점·실점 모델 학습·평가 (out/predictions.parquet, metrics.csv)"),
    ("value",    "src/value.py",           "VAEP 값·선수 랭킹 (out/action_values.parquet, player_ratings.csv)"),
    ("viz",      "src/viz.py",             "공격 장면의 VAEP 변화 그림 (figures/sequence.png)"),
]


def run(script, quiet):
    cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, script)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    tail = collections.deque(maxlen=25)
    t = time.time()
    p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        tail.append(line)
        if not quiet:
            print("   " + line, end="", flush=True)
    code = p.wait()
    if code != 0:
        print("".join("   " + t for t in tail))
        raise SystemExit(f"!! 실패: {script}")
    if quiet and tail:
        print("   " + tail[-1].rstrip())
    return time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", help="이 단계부터 실행")
    ap.add_argument("--only", help="이 단계만 실행")
    ap.add_argument("--list", action="store_true", help="단계 목록만 보기")
    ap.add_argument("-q", "--quiet", action="store_true", help="각 단계의 마지막 줄만 표시")
    args = ap.parse_args()

    names = [n for n, _, _ in PIPELINE]
    if args.list:
        for i, (n, s, d) in enumerate(PIPELINE, 1):
            print(f"{i}. {n:9s} {s:26s} {d}")
        return

    steps = PIPELINE
    if args.only:
        steps = [s for s in PIPELINE if s[0] == args.only]
    elif args.start:
        if args.start not in names:
            raise SystemExit(f"단계 이름이 아니다: {args.start} (가능: {', '.join(names)})")
        steps = PIPELINE[names.index(args.start):]
    if not steps:
        raise SystemExit(f"단계 이름이 아니다 (가능: {', '.join(names)})")

    total = time.time()
    for i, (name, script, desc) in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {name} — {desc}")
        took = run(script, args.quiet)
        print(f"      {took:.0f}초\n")
    print(f"전체 {time.time() - total:.0f}초")


if __name__ == "__main__":
    main()
