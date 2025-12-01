# espn_adapter.py
# ESPN scoreboard adapter for Rewatchability bot (basketball-only).
#
# Public API:
#   get_scoreboard(league_key: str, date_iso: str) -> list[dict]
#   get_final_like_events(...) -> convenience wrapper
#
# We only support:
#   - NBA
#   - WNBA
#
# We also EXCLUDE preseason games explicitly. We only keep:
#   - Regular season
#   - Playoffs / Play-In (non-preseason)

from __future__ import annotations

import os
from typing import Any, Dict, Final, List, Tuple

import requests

DEBUG: bool = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT: float = float(os.getenv("ESPN_TIMEOUT", "8.0"))

USER_AGENT: str = os.getenv(
    "ESPN_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36",
)

HEADERS: Final[dict[str, str]] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Only NBA + WNBA now
LEAGUE_PATH: Final[dict[str, Tuple[str, str]]] = {
    "NBA": ("basketball", "nba"),
    "WNBA": ("basketball", "wnba"),
}


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


def _scoreboard_urls(league_key: str) -> List[str]:
    sport, league = LEAGUE_PATH[league_key]
    return [
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        f"https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _get_json(url: str, params: dict[str, str]) -> Dict[str, Any] | None:
    try:
        _log(f"[DEBUG] GET {url} params={params}")
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            _log(f"[DEBUG] {url} -> {resp.status_code}")
            return None
        return resp.json()
    except Exception as ex:
        _log(f"[DEBUG] request error for {url}: {ex}")
        return None


def _is_final(comp: Dict[str, Any]) -> bool:
    status = (comp.get("status") or {}).get("type") or {}
    state = (status.get("state") or "").lower()
    completed = bool(status.get("completed"))
    return completed and state == "post"


def _is_in_season(comp: Dict[str, Any]) -> bool:
    """
    Return True if this competition is in-season (not preseason).

    ESPN usually encodes:
      - 1 = preseason
      - 2 = regular season
      - 3 = postseason
      - (sometimes 4+ for variants, which we treat as in-season)

    We explicitly drop type == 1.
    If the field is missing/unparseable, we assume in-season.
    """
    season = comp.get("season") or {}
    t = season.get("type")
    try:
        t_int = int(t)
    except (TypeError, ValueError):
        return True  # be permissive if ESPN omits this

    # Exclude preseason only
    return t_int != 1


def _extract_home_away(comp: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    home = None
    away = None
    for c in comp.get("competitors") or []:
        side = (c.get("homeAway") or "").lower()
        if side == "home":
            home = c
        elif side == "away":
            away = c
    return home, away


def _team_fields(team_wrapper: Dict[str, Any]) -> Tuple[str, str]:
    team = team_wrapper.get("team") or {}
    name = team.get("displayName") or team.get("shortDisplayName") or "Team"
    abbr = team.get("abbreviation") or name
    return name, abbr


def _extract_broadcast(comp: Dict[str, Any]) -> str:
    # ESPN sometimes uses "broadcasts", sometimes "geoBroadcasts"
    broadcasts = comp.get("broadcasts") or comp.get("geoBroadcasts") or []
    if not broadcasts:
        return "Streaming / Local"

    b = broadcasts[0] or {}
    return (
        b.get("shortName")
        or b.get("name")
        or b.get("longName")
        or "Streaming / Local"
    )


def get_scoreboard(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Return a normalized scoreboard for a given league/date.

    Each game dict has:
      - id
      - competition_id
      - date (YYYY-MM-DD)
      - league ("NBA"/"WNBA")
      - home, away
      - home_short, away_short
      - broadcast
      - is_final (bool)

    Preseason is EXCLUDED (season.type == 1).
    """
    league_upper = (league_key or "").upper()
    if league_upper not in LEAGUE_PATH:
        raise ValueError(f"Unsupported league_key for ESPN adapter: {league_key!r}")

    dates_param = date_iso.replace("-", "")
    params = {"dates": dates_param}

    data: Dict[str, Any] | None = None
    for url in _scoreboard_urls(league_upper):
        data = _get_json(url, params)
        if data is not None:
            _log(
                f"[INFO] scoreboard OK for {league_upper} on {date_iso} "
                f"via {url} dates={dates_param}"
            )
            break

    if data is None:
        _log(f"[WARN] no scoreboard data for {league_upper} on {date_iso}")
        return []

    events = data.get("events") or []
    out: List[Dict[str, Any]] = []

    for ev in events:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]

        # Drop preseason/exhibition
        if not _is_in_season(comp):
            continue

        home_wrap, away_wrap = _extract_home_away(comp)
        if not home_wrap or not away_wrap:
            continue

        home_name, home_abbr = _team_fields(home_wrap)
        away_name, away_abbr = _team_fields(away_wrap)
        broadcast = _extract_broadcast(comp)

        event_id = str(ev.get("id"))
        comp_id = str(comp.get("id")) if comp.get("id") is not None else None
        date_full = ev.get("date") or ""
        event_date = date_full[:10] if len(date_full) >= 10 else date_iso

        out.append(
            {
                "id": event_id,
                "competition_id": comp_id,
                "date": event_date,
                "league": league_upper,
                "home": home_name,
                "away": away_name,
                "home_short": home_abbr,
                "away_short": away_abbr,
                "broadcast": broadcast,
                "is_final": _is_final(comp),
            }
        )

    return out


def get_final_like_events(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Backwards-compatible helper:
    just filters get_scoreboard(...) down to final games.
    """
    return [g for g in get_scoreboard(league_key, date_iso) if g.get("is_final")]
