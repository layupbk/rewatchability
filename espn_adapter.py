# espn_adapter.py
# ESPN scoreboard adapter for Rewatchability (basketball-only version).
# Public API:
#   get_scoreboard(league_key: str, date_iso: str) -> list[dict]

from __future__ import annotations

import os
from typing import Final, Dict, Any, List, Tuple, Optional

import requests

DEBUG: bool = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT: float = float(os.getenv("ESPN_TIMEOUT", "8.0") or "8.0")

HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# league_key -> (sport_path, league_path)
LEAGUE_PATH: Final[dict[str, Tuple[str, str]]] = {
    "NBA": ("basketball", "nba"),
    "WNBA": ("basketball", "wnba"),
}

# Anything NOT clearly national will be treated as local/streaming
# (we won't show it in the console and won't mark it as "national").
NATIONAL_KEYWORDS: Final[Tuple[str, ...]] = (
    "ESPN",
    "ABC",
    "TNT",
    "TBS",
    "NBA TV",
    "NBATV",
    "FOX",
    "FS1",
    "FS2",
    "CBS",
    "NBC",
    "PEACOCK",
    "AMAZON",
    "PRIME",
    "MAX",
    "HULU",
    "APPLE TV",
    "PARAMOUNT",
    "TRUTV",
)


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


def _scoreboard_urls(league_key: str) -> List[str]:
    sport, league = LEAGUE_PATH[league_key]
    return [
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        f"https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _fetch_scoreboard_json(league_key: str, date_iso: str) -> Optional[Dict[str, Any]]:
    """Try both API hosts for the given league/date; return the first good JSON."""
    if league_key not in LEAGUE_PATH:
        raise ValueError(f"Unsupported league for scoreboard: {league_key!r}")

    dates_param = date_iso.replace("-", "")
    params = {"dates": dates_param}

    for url in _scoreboard_urls(league_key):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
            _log(f"GET {url} params={params} -> {r.status_code}")
            if not r.ok:
                continue
            data = r.json()
            # Sanity check
            if "events" in data:
                _log(
                    f"scoreboard OK for {league_key} on {date_iso} via {url} "
                    f"dates={dates_param}"
                )
                return data
        except Exception as ex:  # defensive
            _log(f"[DEBUG] error fetching scoreboard: {ex}")
            continue

    _log(f"[WARN] no scoreboard data for {league_key} on {date_iso}")
    return None


def _extract_national_network(comp: Dict[str, Any]) -> str:
    """
    Return a single *national* network name if present (ESPN, TNT, etc.),
    else empty string.
    """
    # ESPN sometimes uses "broadcasts" and sometimes "geoBroadcasts"
    broadcasts = comp.get("broadcasts") or comp.get("geoBroadcasts") or []

    for b in broadcasts:
        # Possible fields: 'shortName', 'name', 'network', 'displayName', 'names'
        names: List[str] = []

        if isinstance(b.get("names"), list):
            names.extend([n for n in b["names"] if isinstance(n, str)])

        for key in ("shortName", "name", "network", "displayName"):
            val = b.get(key)
            if isinstance(val, str):
                names.append(val)

        for name in names:
            upper = name.upper()
            if any(keyword in upper for keyword in NATIONAL_KEYWORDS):
                return name.strip()

    return ""


def _extract_teams(competition: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Return (away_info, home_info) with team nicknames & abbreviations based on
    ESPN's own fields. We prefer the *shortDisplayName* because it matches
    the scores page ("Celtics", "Trail Blazers", etc.).
    """
    away_info: Dict[str, Any] = {}
    home_info: Dict[str, Any] = {}

    competitors = competition.get("competitors") or []
    for comp in competitors:
        team = comp.get("team") or {}
        home_away = comp.get("homeAway")

        nickname = (
            team.get("shortDisplayName")
            or team.get("name")
            or team.get("displayName")
            or ""
        ).strip()

        abbreviation = (team.get("abbreviation") or "").strip()

        info = {
            "nickname": nickname,
            "abbr": abbreviation,
        }

        if home_away == "home":
            home_info = info
        elif home_away == "away":
            away_info = info

    return away_info, home_info


def _is_preseason(event: Dict[str, Any]) -> bool:
    """
    ESPN season type codes:
      1 = Preseason
      2 = Regular
      3 = Postseason
      4 = Play-in, etc.
    We exclude type == 1 for NBA/WNBA.
    """
    season = event.get("season") or {}
    stype = season.get("type")
    return stype == 1


def _is_final(event: Dict[str, Any]) -> bool:
    status = (event.get("status") or {}).get("type") or {}
    if status.get("completed") is True:
        return True
    name = status.get("name") or ""
    state = status.get("state") or ""
    return name.startswith("STATUS_FINAL") or state.lower() == "post"


def get_scoreboard(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Return a normalized list of games for the given league & date.

    Each item:
      {
        "id": str (ESPN event id),
        "away": "Celtics",
        "home": "Cavaliers",
        "away_short": "BOS",
        "home_short": "CLE",
        "broadcast": "ESPN" or "" (only national networks),
        "is_final": bool,
      }
    """
    league_key = league_key.upper()
    data = _fetch_scoreboard_json(league_key, date_iso)
    if not data:
        return []

    events = data.get("events") or []
    out: List[Dict[str, Any]] = []

    for ev in events:
        # Filter preseason out
        if _is_preseason(ev):
            continue

        ev_id = ev.get("id")
        if not ev_id:
            continue

        competitions = ev.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]

        away_info, home_info = _extract_teams(comp)

        # If for some reason we couldn't parse team nicknames, skip.
        if not away_info.get("nickname") or not home_info.get("nickname"):
            continue

        broadcast = _extract_national_network(comp)
        is_final = _is_final(ev)

        game_row: Dict[str, Any] = {
            "id": ev_id,
            "away": away_info["nickname"],
            "home": home_info["nickname"],
            "away_short": away_info.get("abbr") or "",
            "home_short": home_info.get("abbr") or "",
            "broadcast": broadcast,  # "" if not national
            "is_final": is_final,
        }
        out.append(game_row)

    _log(f"{len(out)} total {league_key} events on {date_iso}")
    return out
