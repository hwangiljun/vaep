"""StatsBomb open data에서 라리가 2015/16 380경기를 내려받는다.

open-data 저장소와 똑같은 폴더 구조로 받아 두면 socceraction의
StatsBombLoader(getter="local")가 그대로 읽는다.

    data/statsbomb/competitions.json
                  /matches/11/27.json
                  /events/{match_id}.json
                  /lineups/{match_id}.json

이미 받은 파일은 건너뛴다. 중간에 끊겨도 다시 실행하면 이어서 받는다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import COMPETITION_ID, SB_DIR, SEASON_ID  # noqa: E402

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
N_WORKERS = 8
RETRIES = 4


def download(rel_path, dest, min_bytes=2):
    """open-data의 파일 하나를 받아 dest에 저장한다. 이미 있으면 건너뛴다."""
    if os.path.exists(dest) and os.path.getsize(dest) >= min_bytes:
        return "skip"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(f"{BASE}/{rel_path}", timeout=60) as r:
                blob = r.read()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dest)
            return "get"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"다운로드 실패: {rel_path} ({last})")


def main():
    download("competitions.json", os.path.join(SB_DIR, "competitions.json"))
    matches_rel = f"matches/{COMPETITION_ID}/{SEASON_ID}.json"
    matches_dest = os.path.join(SB_DIR, "matches", str(COMPETITION_ID), f"{SEASON_ID}.json")
    download(matches_rel, matches_dest)

    with open(matches_dest, encoding="utf-8") as f:
        matches = json.load(f)
    match_ids = sorted(m["match_id"] for m in matches)
    print(f"경기 {len(match_ids)}개 (competition {COMPETITION_ID} / season {SEASON_ID})")

    jobs = []
    for mid in match_ids:
        jobs.append((f"events/{mid}.json", os.path.join(SB_DIR, "events", f"{mid}.json")))
        jobs.append((f"lineups/{mid}.json", os.path.join(SB_DIR, "lineups", f"{mid}.json")))

    t0, done, got = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        for status in ex.map(lambda j: download(*j), jobs):
            done += 1
            got += status == "get"
            if done % 100 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} 파일 ({time.time() - t0:.0f}초, 새로 받은 것 {got}개)",
                      flush=True)

    size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fs in os.walk(SB_DIR)
        for f in fs
    )
    print(f"완료: {SB_DIR} ({size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
