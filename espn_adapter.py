# espn_adapter.py
# ESPN scoreboard adapter for Rewatchability (basketball-only).
#
# Public API:
#   get_scoreboard(league_key: str, date_iso: str) -> list[dict]
#
# Returns a list of games shaped like:
#   {
#       "id": str,            # ESPN event id
#       "away": str,          # e.g. "Celtics"
#       "home": str,          # e.g. "Lakers"
#       "is_final": bool,     # True if completed/final
#       "broadcast": str,     # national network or "" if local/none
#   }

from __future__ import annotations

import os
from typing import Final, Dict, Any, List

import requests

DEBUG: bool = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT: float = float(os.getenv("ESPN_TIMEOUT", "8.0"))

USER_AGENT: Final[str] = (
    "Mozilla/5.0 (compatible; RewatchabilityBot/1.0; +https://rewatchability)"
)

HEADERS: Final[Dict[str, str]] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# key -> (sport_path, league_path)
LEAGUE_PATH: Final[Dict[str, tuple[str, str]]] = {
    "NBA": ("basketball", "nba"),
    "WNBA": ("basketball", "wnba"),
}

# Optional override of scoreboard base URLs
SCOREBOARD_TEMPLATES_ENV = os.getenv("ESPN_SCOREBOARD_BASES")  # comma-separated


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


def _scoreboard_templates() -> List[str]:
    """
    List of scoreboard base URLs with {sport} and {league} placeholders.

    If ESPN_SCOREBOARD_BASES is set, use that (comma-separated).
    Otherwise, use known-good defaults.
    """
    if SCOREBOARD_TEMPLATES_ENV:
        tmpls = [t.strip() for t in SCOREBOARD_TEMPLATES_ENV.split(",") if t.strip()]
        if tmpls:
            return tmpls

    return [
        "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        "https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _scoreboard_urls(league_key: str) -> List[str]:
    sport, league = LEAGUE_PATH[league_key]
    return [tmpl.format(sport=sport, league=league) for tmpl in _scoreboard_templates()]


def _get(url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        if not r.ok:
            _log(f"[DEBUG] GET {url} params={params} -> {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        _log(f"[DEBUG] GET error for {url}: {e}")
        return None


def _espn_date_param(date_iso: str) -> str:
    """
    ESPN supports both YYYYMMDD and YYYY-MM-DD; we use YYYYMMDD.
    """
    return date_iso.replace("-", "")


def _is_final_status(status: Dict[str, Any]) -> bool:
    """
    Decide if an event is 'final-like' based on ESPN status.
    """
    t = status.get("type") or {}
    if t.get("completed"):
        return True
    name = (t.get("name") or "").upper()
    if name in ("STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_POSTPONED"):
        return True
    return False


def _pick_team_name(team: Dict[str, Any]) -> str:
    """
    Prefer the nickname/shortDisplayName used on the scores page,
    e.g. "Celtics" instead of "Boston Celtics".
    """
    return (
        team.get("shortDisplayName")
        or team.get("nickname")
        or team.get("name")
        or team.get("displayName")
        or ""
    ).strip()


def _pick_national_broadcast(comp: Dict[str, Any]) -> str:
    """
    From ESPN 'broadcasts', choose a national/international network string.
    If everything is local/regional, return "".
    """
    broadcasts = comp.get("broadcasts") or []
    names: set[str] = set()

    for b in broadcasts:
        market = (b.get("market") or "").lower()
        is_nat = market in ("national", "international") or bool(b.get("isNational"))
        if not is_nat:
            continue

        # 'names' is usually a list like ["ESPN", "ESPN2"]
        for nm in b.get("names") or []:
            nm = (nm or "").strip()
            if nm:
                names.add(nm)

        # Some feeds also provide a 'shortName'
        short_name = (b.get("shortName") or "").strip()
        if short_name:
            names.add(short_name)

    if not names:
        return ""

    # Deterministic order
    return " / ".join(sorted(names))


def get_scoreboard(league_key: str, date_iso: str) -> list[dict]:
    """
    Fetch ESPN scoreboard for NBA or WNBA for a given date (YYYY-MM-DD).

    Returns a list of dicts:
      {
          "id": str,
          "away": str,
          "home": str,
          "is_final": bool,
          "broadcast": str,  # national / international only, else ""
      }
    """
    league_key = league_key.upper()
    if league_key not in LEAGUE_PATH:
        _log(f"[WARN] unsupported league for get_scoreboard: {league_key}")
        return []

    date_param = _espn_date_param(date_iso)

    data: Dict[str, Any] | None = None
    urls = _scoreboard_urls(league_key)

    for u in urls:
        params = {"dates": date_param}
        d = _get(u, params=params)
        if d and d.get("events"):
            _log(
                f"[INFO] scoreboard OK for {league_key} on {date_iso} "
                f"via {u} dates={date_param}"
            )
            data = d
            break

    if not data or not data.get("events"):
        _log(f"[WARN] no scoreboard data for {league_key} on {date_iso}")
        return []

    games_out: list[dict] = []
    events = data.get("events") or []

    for e in events:
        comps = e.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]

        # Skip preseason if season.type == 1 (when present)
        season = comp.get("season") or e.get("season") or {}
        if season.get("type") == 1:
            continue  # preseason

        status = comp.get("status") or e.get("status") or {}
        is_final = _is_final_status(status)

        # Extract teams
        competitors = comp.get("competitors") or []
        away_name = ""
        home_name = ""
        for c in competitors:
            team = c.get("team") or {}
            nm = _pick_team_name(team)
            side = (c.get("homeAway") or "").lower()
            if side == "home":
                home_name = nm
            elif side == "away":
                away_name = nm

        event_id = str(e.get("id") or comp.get("id") or "").strip()
        if not event_id:
            continue

        broadcast = _pick_national_broadcast(comp)

        games_out.append(
            {
                "id": event_id,
                "away": away_name,
                "home": home_name,
                "is_final": bool(is_final),
                "broadcast": broadcast,
            }
        )

    _log(f"[ESPN] {len(games_out)} total {league_key} events on {date_iso}")
    return games_out
