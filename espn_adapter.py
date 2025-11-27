# espn_adapter.py
# ESPN scoreboard + win-probability adapter for Rewatchability bot.
# Uses ESPN's unofficial "site.api" scoreboard endpoints.
# Public API: get_final_like_events(), fetch_wp_quick().

from __future__ import annotations

import os
import requests
from typing import Final

# -----------------------------
# Config
# -----------------------------
DEBUG: bool = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT: float = float(os.getenv("ESPN_TIMEOUT", "8.0"))

# NOTE: We only support a small set of sports/leagues that we explicitly
# calibrate and test for this project.

# key -> (sport_path, league_path)
LEAGUE_PATH: Final[dict[str, tuple[str, str]]] = {
    "NBA":   ("basketball", "nba"),
    "NFL":   ("football",   "nfl"),
    "MLB":   ("baseball",   "mlb"),
    "NCAAF": ("football",   "college-football"),
    "NCAAM": ("basketball", "mens-college-basketball"),
    "NCAAB": ("basketball", "mens-college-basketball"),  # alias for NCAAM
    "CBB":   ("basketball", "mens-college-basketball"),  # optional college hoops alias
}

# Query param name ESPN uses for dates on scoreboard
DATE_PARAM: str = os.getenv("ESPN_DATE_PARAM", "dates")

# Optional override for scoreboard base URLs, comma-separated.
# Each template must contain {sport} and {league}.
SCOREBOARD_TEMPLATES_ENV: str | None = os.getenv("ESPN_SCOREBOARD_BASES")


# -----------------------------
# Logging helpers
# -----------------------------
def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


# -----------------------------
# URL helpers
# -----------------------------
def _default_scoreboard_templates() -> list[str]:
    # Primary: site.api
    # Secondary: site.web.api (used by some clients)
    return [
        "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        "https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _scoreboard_templates() -> list[str]:
    """
    List of scoreboard base URLs with {sport} and {league} placeholders.

    Uses env override if ESPN_SCOREBOARD_BASES is set, otherwise falls back
    to the default pair of site.api + site.web.api.
    """
    if SCOREBOARD_TEMPLATES_ENV:
        templates = []
        for piece in SCOREBOARD_TEMPLATES_ENV.split(","):
            tpl = piece.strip()
            if not tpl:
                continue
            if "{sport}" not in tpl or "{league}" not in tpl:
                continue
            templates.append(tpl)
        if templates:
            return templates
    return _default_scoreboard_templates()


def _scoreboard_urls_for_league(league_key: str) -> list[str]:
    league_key = league_key.upper()
    if league_key not in LEAGUE_PATH:
        return []
    sport, league = LEAGUE_PATH[league_key]
    urls = []
    for tpl in _scoreboard_templates():
        urls.append(tpl.format(sport=sport, league=league))
    return urls


def _summary_url_for_event(league_key: str, event_id: str) -> str | None:
    """
    Build an ESPN "summary" URL for a single event given a league key.
    """
    league_key = league_key.upper()
    if league_key not in LEAGUE_PATH:
        return None
    sport, league = LEAGUE_PATH[league_key]
    return f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary"


# -----------------------------
# HTTP helper
# -----------------------------
def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        if not r.ok:
            _log(f"[DEBUG] GET {url} params={params} -> {r.status_code}")
            return None
        return r.json()
    except Exception as e:  # defensive
        _log(f"[DEBUG] GET error for {url}: {e}")
        return None


# -----------------------------
# Scoreboard adapter
# -----------------------------

# Some ESPN sports (notably college football) require a "group" param to
# scope the scoreboard. We support a minimal set here and can expand later.
LEAGUE_GROUPS: Final[dict[str, str]] = {
    # College football top-level "FBS" group
    "NCAAF": "80",
}

# Some sports have a limit param that must be set high enough to capture
# all games on busy days.
LEAGUE_LIMITS: Final[dict[str, str]] = {
    "NCAAF": "500",
}


def _scoreboard_params_for_league(league_key: str, date_iso: str) -> dict:
    league_key = league_key.upper()
    params: dict[str, str] = {DATE_PARAM: date_iso.replace("-", "")}
    if league_key in LEAGUE_GROUPS:
        params["groups"] = LEAGUE_GROUPS[league_key]
    if league_key in LEAGUE_LIMITS:
        params["limit"] = LEAGUE_LIMITS[league_key]
    return params


def _extract_competitions(scoreboard: dict) -> list[dict]:
    events = scoreboard.get("events") or []
    comps: list[dict] = []
    for ev in events:
        for comp in ev.get("competitions") or []:
            comps.append(comp)
    return comps


def _is_final_like(status: dict) -> bool:
    """
    Treat "final", "status over", and similar as end-of-game.
    """
    if not status:
        return False
    type_info = status.get("type") or {}
    # ESPN uses a numeric id and a name like "STATUS_FINAL".
    name = (type_info.get("name") or "").upper()
    description = (type_info.get("description") or "").upper()
    state = (type_info.get("state") or "").upper()

    # Basic check: state is "post"
    if state == "POST":
        return True

    # Fallback: look at name/description
    final_keywords = ("FINAL", "OVERTIME", "AFTER")
    if any(k in name for k in final_keywords):
        return True
    if any(k in description for k in final_keywords):
        return True

    return False


def _extract_broadcast(comp: dict) -> str:
    """
    Return a best-effort network string. Fallback to empty if not found.
    """
    broadcast = ""
    # ESPN scoreboard often has a "broadcasts" list
    for b in comp.get("broadcasts") or []:
        name = b.get("name") or ""
        network = b.get("shortName") or b.get("name") or ""
        if network:
            broadcast = network
            break

    if not broadcast:
        # Sometimes it's under "geoBroadcasts"
        for gb in comp.get("geoBroadcasts") or []:
            media = gb.get("media") or {}
            network = media.get("shortName") or media.get("name") or ""
            if network:
                broadcast = network
                break

    return broadcast


def _extract_comp_info(comp: dict) -> dict | None:
    status = comp.get("status") or {}
    if not _is_final_like(status):
        return None

    competition_id = comp.get("id")
    if not competition_id:
        return None

    # ESPN events also have a top-level "id". We flow that through as event_id.
    event_id = None
    # Some scoreboards propagate it; others we might have to inspect parent.
    # For simplicity, we let caller attach it if needed; here we just carry
    # competition id and leave event_id placeholder.
    # In this adapter, we treat competition_id as the primary id.
    # The main script often uses the "event" id for formatting links, so
    # we pass both when possible.

    # Score / teams
    comp_data: dict = {
        "competition_id": competition_id,
        "event_id": comp.get("id"),
        "status": status,
    }

    # Simplified team names + scores
    home = None
    away = None

    for c in comp.get("competitors") or []:
        team = c.get("team") or {}
        is_home = c.get("homeAway") == "home"
        # Use displayName as a default; fallback to "shortDisplayName" etc.
        name = (
            team.get("displayName")
            or team.get("shortDisplayName")
            or team.get("name")
            or ""
        )
        abbrev = team.get("abbreviation") or ""
        score = c.get("score")
        record = ""
        if c.get("records"):
            record = c["records"][0].get("summary") or ""

        entry = {
            "name": name,
            "abbrev": abbrev,
            "score": score,
            "record": record,
            "is_home": is_home,
            "id": team.get("id"),
        }

        if is_home:
            home = entry
        else:
            away = entry

    comp_data["home"] = home
    comp_data["away"] = away
    comp_data["broadcast"] = _extract_broadcast(comp)

    return comp_data


def get_final_like_events(league_key: str, date_iso: str) -> list[dict]:
    """
    Return a list of games (competitions) that look "final" for a league+date.

    Each element is a dict with:
        - competition_id
        - event_id (if available)
        - status (raw ESPN status dict)
        - home: { name, abbrev, score, record, is_home, id }
        - away: { ... }
        - broadcast: "TNT", "ESPN", etc. (best effort)
    """
    league_key = league_key.upper()
    if league_key not in LEAGUE_PATH:
        _log(f"[WARN] league_key {league_key!r} not configured")
        return []

    urls = _scoreboard_urls_for_league(league_key)
    params = _scoreboard_params_for_league(league_key, date_iso)

    final_games: list[dict] = []
    any_success = False

    for url in urls:
        data = _get(url, params=params)
        if not data:
            continue
        any_success = True
        comps = _extract_competitions(data)
        for comp in comps:
            info = _extract_comp_info(comp)
            if info:
                final_games.append(info)

        if final_games:
            break

    if not any_success:
        _log(f"[WARN] no scoreboard data for {league_key} on {date_iso}")
    else:
        _log(
            f"[INFO] {date_iso} FINAL-like events found: {len(final_games)}",
        )

    return final_games


# -----------------------------
# Win probability (WP) adapter
# -----------------------------

HEADERS: dict = {
    "User-Agent": "RewatchabilityBot/1.0 (https://rewatchability.com)",
}


def _extract_wp_series_from_summary(summary: dict) -> list[float]:
    """
    Extract a home-team win probability series from an ESPN summary JSON.

    Returns a list of floats in [0, 1]. If anything goes wrong, returns [].
    """
    # Path to WP chart depends on sport; we handle the known structure:
    # summary["winprobability"]["homeWinPercentage"] with "value" fields.
    wp_root = summary.get("winprobability") or {}
    series: list[float] = []

    for point in wp_root.get("homeWinPercentage") or []:
        val = point.get("value")
        if val is None:
            continue
        try:
            f = float(val)
        except Exception:
            continue
        series.append(f)

    return series


def fetch_wp_quick(league_key: str, event_id: str) -> list[float]:
    """
    Fetch a quick WP series for a single event by hitting the summary API.

    We return a list of *home-team* win probabilities in [0, 1]. If anything
    fails, we return [].
    """
    league_key = league_key.upper()
    url = _summary_url_for_event(league_key, event_id)
    if not url:
        _log(f"[WARN] no summary URL for league {league_key}")
        return []

    params = {"event": event_id}
    summary = _get(url, params=params)
    if not summary:
        return []

    series_raw = _extract_wp_series_from_summary(summary)
    if not series_raw:
        _log(f"[DEBUG] no WP series for {league_key} {event_id}")
        return []

    # Normalize to [0, 1]; some feeds may be 0–100 percentages.
    series: list[float] = []
    for val in series_raw:
        if val > 1.0:
            val = val / 100.0
        if val < 0.0 or val > 1.0:
            continue
        series.append(val)

    _log(f"[INFO] WP series points: {len(series)} for {league_key} {event_id}")
    return series
