# espn_adapter.py
# Full + Debug version
# Robust ESPN scoreboard + WP fetch with fallbacks and clear logs.
# Works for NBA, NFL, MLB now; safe to extend to NCAAM/NCAAF later.

from __future__ import annotations
import os, time, typing as t
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

# Supported leagues and their ESPN path fragments
LEAGUE_PATH = {
    "NBA":   ("basketball", "nba"),
    "NFL":   ("football",   "nfl"),
    "MLB":   ("baseball",   "mlb"),
    "NCAAM": ("basketball", "mens-college-basketball"),
    "NCAAF": ("football",   "college-football"),
}

# Known national networks (fallback only — primary is ESPN’s own flags)
NATIONAL_NETWORKS = {
    # Broadcasters
    "ABC", "CBS", "FOX", "NBC",
    "ESPN", "ESPN2", "ESPNU", "ESPNEWS",
    "TNT", "TBS", "truTV",
    "FS1", "FS2", "Peacock", "Peacock Premium",
    "CBS Sports Network", "CBSSN",
    "Prime Video", "Amazon Prime", "Amazon",
    "NFL Network", "NFLN",
    "NBA TV", "NBATV",
    "B/R Sports", "Bleacher Report",
    # Conference nets (you asked to treat "+" as national; we follow ESPN flag first)
    "SEC Network", "SEC Network+", "SECN", "SECN+",
    "Big Ten Network", "BTN",
    "ACC Network", "ACCN",
    "Pac-12 Network", "P12N",
    "B1G+", "B1G Plus",
}

def _log(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)

def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            _log(f"[DEBUG] GET {r.url} -> {r.status_code}")
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

    # Newer site APIs (order matters)
    urls: list[str] = [
        # Site API v2 (newer style for many pages)
        f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/scoreboard",
        # Legacy-ish site API
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        # Core API (sometimes stricter CORS but works from server)
        f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/events",
    ]

    # Attach date param on ones that accept it
    yyyymmdd = date_iso.replace("-", "")
    urls_with_params = []
    for u in urls:
        if "scoreboard" in u:
            urls_with_params.append(f"{u}?dates={yyyymmdd}")
        else:
            # core events endpoint uses a different structure; we’ll filter by date later
            urls_with_params.append(u)
    return urls_with_params

def _is_national_from_comp(comp: dict) -> tuple[bool, str | None]:
    """
    Use ESPN competition broadcasts block to determine if national.
    Return (is_national, network_short).
    """
    try:
        broadcasts = comp.get("broadcasts") or []
        for b in broadcasts:
            market = (b.get("market") or "").lower()
            # ESPN’s own marker is best
            if market == "national":
                name = b.get("names") or b.get("name") or b.get("shortName") or b.get("station")
                short = None
                if isinstance(name, list) and name:
                    short = str(name[0])
                elif isinstance(name, str):
                    short = name
                else:
                    short = b.get("shortName") or b.get("station")
                return True, (short or "").strip() or None
        # No explicit national flag, try to extract a recognizable network
        for b in broadcasts:
            short = b.get("shortName") or b.get("station") or b.get("name")
            if isinstance(short, list) and short:
                short = short[0]
            if isinstance(short, str):
                cand = short.strip()
                if cand in NATIONAL_NETWORKS:
                    return True, cand
        return False, None
    except Exception:
        return False, None

def _parse_event(e: dict, league_key: str) -> dict | None:
    """
    Normalize an ESPN event from scoreboard into our schema.
    Expected output keys:
      sport, road, home, network, neutral_site, event_name, event_id, comp_id, completed
    """
    try:
        competitions = e.get("competitions") or []
        if not competitions:
            return None
        comp = competitions[0]
        comp_id = str(comp.get("id") or e.get("id") or "")
        event_id = str(e.get("id") or comp_id)

        # Teams
        road = home = ""
        for c in (comp.get("competitors") or []):
            team = c.get("team") or {}
            name = team.get("displayName") or team.get("name") or team.get("shortDisplayName") or ""
            if c.get("homeAway") == "home":
                home = name
            else:
                road = name

        # Neutral site
        neutral = bool(comp.get("neutralSite"))

        # Event or tournament name
        event_name = e.get("name") or comp.get("name") or ""

        # National TV?
        is_nat, net = _is_national_from_comp(comp)
        network = net if is_nat else None

        # Status check
        status = (e.get("status") or {}).get("type") or {}
        state = (status.get("state") or "").lower()  # "post", "in", "pre"
        completed = state == "post"

        return {
            "sport": league_key,
            "road": road,
            "home": home,
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

def _looks_final_like(ev: dict) -> bool:
    """
    Conservative 'final-like' check: explicitly completed.
    """
    return bool(ev.get("completed"))

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
            data = _get(u)
            if data:
                break
        if not data:
            _log(f"[DEBUG] scoreboard load failed for {league}")
            continue

        # Scoreboard shape variants: 'events' (site API) or 'items' (core API chain)
        events = data.get("events") or data.get("items") or []
        if isinstance(events, dict):
            events = []

        found = finals = 0
        for e in events:
            found += 1
            ev = _parse_event(e, league)
            if not ev:
                continue
            if _looks_final_like(ev):
                finals += 1
                out.append(ev)

        _log(f"[DEBUG] {league} events={found}")
        _log(f"[DEBUG] {league} finals_like={finals}")

    _log(f"[INFO] {date_iso} FINAL-like events found: {len(out)}")
    return out

# -----------------------------
# Public helpers expected by main.py
# -----------------------------

def _to_iso(date_str: str) -> str:
    """Accept 'YYYYMMDD' or 'YYYY-MM-DD'; return 'YYYY-MM-DD'."""
    s = date_str.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s

def get_final_like_events(sport_lower: str, date_str: str) -> list[dict]:
    """
    main.py calls this. It returns a list of dicts shaped for posting:
      { id, competition_id, away, home, broadcast }
    """
    sport_up = sport_lower.upper()
    iso = _to_iso(date_str)
    # Ask only for this sport to keep things light
    raw = list_final_events_for_date(iso, [sport_up])

    out: list[dict] = []
    for ev in raw:
        # Map to the shape main.py expects
        out.append({
            "id": ev["event_id"],
            "competition_id": ev["comp_id"],
            "away": ev["road"],
            "home": ev["home"],
            "broadcast": ev["network"],  # None or short name
        })
    return out

# -----------------------------
# Win probability fetch
# -----------------------------
def _summary_urls(league_key: str, event_id: str) -> list[str]:
    sport, league = LEAGUE_PATH[league_key]
    # Try summary first, then pbp
    return [
        f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/summary?event={event_id}",
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event_id}",
        f"https://site.web.api.espn.com/apis/v2/sports/{sport}/{league}/playbyplay?event={event_id}",
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/playbyplay?event={event_id}",
    ]

def _extract_wp_series(obj: dict) -> list[float] | None:
    """
    Look for a winProbability-style series of home-team probabilities (0..1).
    """
    # Common: summary.winprobability[]
    try:
        wp = obj.get("winprobability")
        if isinstance(wp, list) and wp:
            series: list[float] = []
            for pt in wp:
                p = pt.get("homeWinPercentage") or pt.get("homeWinProb")
                if p is None:
                    continue
                val = float(p)
                if val > 1.0:
                    val /= 100.0
                series.append(max(0.0, min(1.0, val)))
            if series:
                return series
    except Exception:
        pass

    # Sometimes under play-by-play "plays"
    try:
        plays = obj.get("plays") or []
        if isinstance(plays, list) and plays:
            series: list[float] = []
            for pl in plays:
                p = pl.get("homeWinProbability") or pl.get("homeWinPercentage")
                if p is None:
                    continue
                val = float(p)
                if val > 1.0:
                    val /= 100.0
                series.append(max(0.0, min(1.0, val)))
            if series:
                return series
    except Exception:
        pass

    return None

def fetch_win_probability_series(league_key: str, event_id: str, comp_id: str | None) -> list[float] | None:
    """Try several endpoints to get a home-win-probability series."""
    for url in _summary_urls(league_key, event_id):
        obj = _get(url)
        if not obj:
            continue
        series = _extract_wp_series(obj)
        if series:
            _log(f"[DEBUG] WP series length={len(series)} for {event_id}")
            return series
    _log(f"[DEBUG] WP series not found for {event_id}")
    return None

# Quick retry wrapper the main loop can call
def fetch_wp_quick(sport_lower: str, event_id: str, comp_id: str | None) -> list[float] | None:
    """Retry a few times quickly for late-arriving WP after final."""
    schedule = [0, 10, 20, 35]  # seconds
    league_key = sport_lower.upper()
    start = time.time()
    for i, target in enumerate(schedule):
        sleep_for = target - (time.time() - start)
        if sleep_for > 0:
            time.sleep(sleep_for)
        series = fetch_win_probability_series(league_key, event_id, comp_id)
        if series:
            if i > 0:
                _log(f"[DEBUG] WP arrived on quick attempt {i+1}/{len(schedule)}")
            return series
    return None
