# espn_adapter.py
# Full + Debug version
# Robust ESPN scoreboard + WP fetch with fallbacks and clear logs.
# Works for NBA, NFL, MLB, NCAAF, NCAAM.

from __future__ import annotations
import os
import requests

# -----------------------------
# Config
# -----------------------------
DEBUG = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT = float(os.getenv("ESPN_TIMEOUT", "8.0"))

USER_AGENT = os.getenv(
    "ESPN_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Supported leagues for scoreboards / summaries
LEAGUE_PATH: dict[str, tuple[str, str]] = {
    # sport,     league
    "NBA":   ("basketball", "nba"),
    "NFL":   ("football",   "nfl"),
    "MLB":   ("baseball",   "mlb"),
    "NCAAF": ("football",   "college-football"),
    "NCAAM": ("basketball", "mens-college-basketball"),
}

# -----------------------------
# Logging helpers
# -----------------------------
def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


# -----------------------------
# HTTP helpers
# -----------------------------
def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        if not r.ok:
            _log(f"[DEBUG] GET {url} -> {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        _log(f"[DEBUG] GET error for {url}: {e}")
        return None


def _scoreboard_urls(sport_key: str, date_iso: str) -> list[str]:
    """
    Return a list of candidate scoreboard endpoints to try, new to old.
    """
    sport, league = LEAGUE_PATH[sport_key]

    urls: list[str] = [
        f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/scoreboard",
        f"https://site.api.espn.com/apis/v2/sports/{sport}/{league}/scoreboard",
        f"https://sportscenter.api.espn.com/apis/v1/events",
    ]
    return urls


def _summary_urls(league_key: str, event_id: str) -> list[str]:
    """
    Return a list of candidate summary endpoints to try for WP play-by-play.
    """
    sport, league = LEAGUE_PATH[league_key]
    return [
        f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/summary/{event_id}",
        f"https://site.api.espn.com/apis/v2/sports/{sport}/{league}/summary",
    ]


# -----------------------------
# Helpers for scoreboard parsing
# -----------------------------
def _is_national_from_comp(comp: dict) -> tuple[bool, str | None]:
    """
    Guess if a game is on national TV by inspecting 'broadcasts' on a competition.
    Return (is_nat, network_short_name).
    """
    broadcasts = comp.get("broadcasts") or []
    if not broadcasts:
        return False, None

    best_name = None
    for b in broadcasts:
        market = (b.get("market") or "").lower()
        names = b.get("names") or []
        if not names and "broadcasters" in b:
            names = [br.get("shortName") or br.get("name") for br in (b["broadcasters"] or [])]

        short = None
        for n in names:
            if not n:
                continue
            short = str(n)
            break

        if not short:
            continue

        if market == "national":
            return True, short

        if not best_name:
            best_name = short

    if best_name:
        return True, best_name

    return False, None


def _parse_event(league_key: str, comp: dict, e: dict) -> dict | None:
    """
    Normalize one ESPN event/competition into a compact dict we can use later.

    Returns:
      {
        "sport": league_key,
        "road": str,
        "home": str,
        "road_short": str,
        "home_short": str,
        "network": str|None,
        "neutral_site": bool,
        "event_name": str,
        "event_id": str,
        "comp_id": str,
        "completed": bool,
      }
    """
    try:
        event_id = str(e.get("id") or "")
        comp_id = str(comp.get("id") or event_id)

        road = home = ""
        road_short = home_short = ""
        for c in (comp.get("competitors") or []):
            team = c.get("team") or {}
            long_name = (
                team.get("displayName")
                or team.get("name")
                or team.get("shortDisplayName")
                or ""
            )
            short_name = (
                team.get("shortDisplayName")
                or team.get("displayName")
                or team.get("name")
                or ""
            )
            if c.get("homeAway") == "home":
                home = long_name
                home_short = short_name
            else:
                road = long_name
                road_short = short_name

        neutral = bool(comp.get("neutralSite"))
        event_name = e.get("name") or comp.get("name") or ""

        is_nat, net = _is_national_from_comp(comp)
        network = net if is_nat else None

        status = (e.get("status") or {}).get("type") or {}
        state = (status.get("state") or "").lower()
        completed = state == "post"

        return {
            "sport": league_key,
            "road": road,
            "home": home,
            "road_short": road_short or road,
            "home_short": home_short or home,
            "network": network,
            "neutral_site": neutral,
            "event_name": event_name,
            "event_id": event_id,
            "comp_id": comp_id,
            "completed": completed,
        }
    except Exception as ex:
        _log(f"[DEBUG] parse event error: {ex}")
        return None


def list_final_events_for_date(date_iso: str, leagues: list[str]) -> list[dict]:
    """
    Return normalized events for leagues that look 'final-like' on date (YYYY-MM-DD).
    """
    out: list[dict] = []

    for league in leagues:
        if league not in LEAGUE_PATH:
            continue

        urls = _scoreboard_urls(league, date_iso)
        data = None
        for u in urls:
            params = {"dates": date_iso} if "scoreboard" in u else None
            data = _get(u, params=params)
            if data:
                break
        if not data:
            _log(f"[WARN] no scoreboard data for {league} on {date_iso}")
            continue

        events = data.get("events") or []
        for e in events:
            comps = e.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            parsed = _parse_event(league, comp, e)
            if not parsed:
                continue
            if parsed["completed"]:
                out.append(parsed)

    _log(f"[INFO] {date_iso} FINAL-like events found: {len(out)}")
    return out


# -----------------------------
# Public helpers expected by main.py
# -----------------------------
def _to_iso(date_str: str) -> str:
    s = date_str.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


def get_final_like_events(sport_lower: str, date_str: str) -> list[dict]:
    """
    main.py calls this. It returns a list of dicts shaped for posting:
      { id, competition_id, away, home, away_short, home_short, broadcast }
    """
    sport_up = sport_lower.upper()
    iso = _to_iso(date_str)
    raw = list_final_events_for_date(iso, [sport_up])

    out: list[dict] = []
    for ev in raw:
        out.append({
            "id": ev["event_id"],
            "competition_id": ev["comp_id"],
            "away": ev["road"],
            "home": ev["home"],
            "away_short": ev.get("road_short") or ev["road"],
            "home_short": ev.get("home_short") or ev["home"],
            "broadcast": ev["network"],
        })
    return out


# -----------------------------
# Win probability fetch
# -----------------------------
def fetch_wp_quick(sport_lower: str, event_id: str, comp_id: str | None) -> list[float]:
    """
    Fetch win-probability series for the HOME team for a given event/competition.
    Returns a list of floats in [0,1], or [] on error.
    """
    league_key = sport_lower.upper()
    if league_key not in LEAGUE_PATH:
        _log(f"[WARN] unknown sport for WP fetch: {sport_lower}")
        return []

    urls = _summary_urls(league_key, event_id)
    data = None

    for u in urls:
        if "summary?" in u:
            data = _get(u, params={"event": event_id})
        else:
            data = _get(u)
        if data:
            break

    if not data:
        _log(f"[WARN] no summary data for {league_key} event={event_id}")
        return []

    try:
        wp_list = data.get("winprobability") or data.get("winProbability") or []
        if not wp_list:
            _log("[DEBUG] no winprobability array present")
            return []

        series: list[float] = []
        for pt in wp_list:
            home_wp = (
                pt.get("homeWinPercentage")
                or pt.get("homeWinProb")
                or pt.get("homeWinProbability")
            )
            if home_wp is None:
                continue
            try:
                v = float(home_wp)
            except (TypeError, ValueError):
                continue
            series.append(v)

        _log(f"[INFO] WP series points: {len(series)} for {league_key} {event_id}")
        return series
    except Exception as ex:
        _log(f"[DEBUG] parse WP error: {ex}")
        return []
