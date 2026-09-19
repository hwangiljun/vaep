"""StatsBomb 원본 이벤트를 SPADL 행동으로 변환한다.

    data/statsbomb/*  ->  out/games.parquet, teams.parquet, players.parquet,
                          player_games.parquet, actions.parquet

SPADL은 공급자마다 다른 이벤트 표기를 <선수, 팀, 시간, 시작위치, 끝위치, 행동유형,
결과, 신체부위> 하나로 통일한 표기다. 경기 하나가 대략 1,600~1,800개 행동이 된다.
"""
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import COMPETITION_ID, OUT, SB_DIR, SEASON_ID  # noqa: E402

warnings.filterwarnings("ignore")

N_WORKERS = 16
_loader = None


def patch_missing_locations():
    """socceraction 1.5.3의 좌표 변환 버그를 막는다.

    `_convert_locations`는 `np.empty`로 좌표 배열을 잡고 위치가 있는 이벤트만 채운다.
    위치가 빠진 이벤트(주로 골키퍼 이벤트)의 행은 초기화되지 않은 메모리 값으로 남아,
    실행할 때마다 다른 좌표가 나오고 결과가 재현되지 않는다. 그런 행은 NaN으로 둔다.
    (757,310개 행동 중 열 개 남짓이지만, 그 한 줄 때문에 모델이 매번 달라진다.)
    """
    import numpy as np
    import socceraction.spadl.statsbomb as sb

    if getattr(sb._convert_locations, "_patched", False):
        return
    original = sb._convert_locations

    def convert_locations(locations, fidelity_version):
        out = original(locations, fidelity_version)
        filled = locations.apply(lambda loc: isinstance(loc, list) and len(loc) in (2, 3))
        out[~filled.to_numpy()] = np.nan
        return out

    convert_locations._patched = True
    sb._convert_locations = convert_locations


def loader():
    """프로세스마다 로더를 하나씩 만든다."""
    global _loader
    if _loader is None:
        from socceraction.data.statsbomb import StatsBombLoader

        _loader = StatsBombLoader(getter="local", root=SB_DIR)
    return _loader


def one_game(args):
    """경기 하나를 SPADL로 바꾸고, 팀·선수 정보도 함께 돌려준다."""
    import socceraction.spadl as spadl

    game_id, home_team_id = args
    patch_missing_locations()
    sbl = loader()
    teams = sbl.teams(game_id)
    players = sbl.players(game_id)
    events = sbl.events(game_id)
    actions = spadl.statsbomb.convert_to_actions(events, home_team_id=home_team_id)
    return teams, players, actions


def main():
    from socceraction.data.statsbomb import StatsBombLoader

    sbl = StatsBombLoader(getter="local", root=SB_DIR)
    competitions = sbl.competitions()
    competitions = competitions[
        (competitions.competition_id == COMPETITION_ID) & (competitions.season_id == SEASON_ID)
    ]
    games = (sbl.games(COMPETITION_ID, SEASON_ID)
             .sort_values(["game_date", "game_id"])   # 같은 날 경기가 많아 타이브레이크까지 고정한다
             .reset_index(drop=True))
    print(f"경기 {len(games)}개: {games.game_date.min():%Y-%m-%d} ~ {games.game_date.max():%Y-%m-%d}")

    t0 = time.time()
    jobs = [(g.game_id, g.home_team_id) for g in games.itertuples()]
    teams, players, actions = [], [], []
    with ProcessPoolExecutor(max_workers=N_WORKERS) as ex:
        for i, (t, p, a) in enumerate(ex.map(one_game, jobs), 1):
            teams.append(t)
            players.append(p)
            actions.append(a)
            if i % 50 == 0 or i == len(jobs):
                print(f"  변환 {i}/{len(jobs)}경기 ({time.time() - t0:.0f}초)", flush=True)

    teams = pd.concat(teams).drop_duplicates(subset="team_id").reset_index(drop=True)
    players = pd.concat(players).reset_index(drop=True)
    actions = pd.concat(actions).reset_index(drop=True)

    # 선수 이름은 경기마다 같으므로 한 번만, 출전 기록은 경기별로 따로 저장한다
    player_names = players[["player_id", "player_name", "nickname"]].drop_duplicates("player_id")
    player_games = players[
        ["player_id", "game_id", "team_id", "is_starter", "starting_position_name", "minutes_played"]
    ]

    competitions.to_parquet(os.path.join(OUT, "competitions.parquet"))
    games.to_parquet(os.path.join(OUT, "games.parquet"))
    teams.to_parquet(os.path.join(OUT, "teams.parquet"))
    player_names.to_parquet(os.path.join(OUT, "players.parquet"))
    player_games.to_parquet(os.path.join(OUT, "player_games.parquet"))
    actions.to_parquet(os.path.join(OUT, "actions.parquet"))

    import socceraction.spadl as spadl

    named = spadl.add_names(actions)
    missing = actions[["start_x", "start_y", "end_x", "end_y"]].isna().any(axis=1).sum()
    print(f"행동 {len(actions):,}개, 경기당 평균 {len(actions) / len(games):.0f}개"
          f" (좌표가 없는 행동 {missing}개는 NaN)")
    print(f"골 {int(((named.type_name.str.contains('shot')) & (named.result_name == 'success')).sum())}개"
          f", 선수 {players.player_id.nunique()}명, 팀 {len(teams)}개")
    print(f"저장: {OUT}/actions.parquet ({os.path.getsize(os.path.join(OUT, 'actions.parquet')) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
