# espn_adapter.py
# Robust ESPN fetcher with browser-like headers, retries, and fallbacks.
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import requests

# ---------- Config ----------
READ_TIMEOUT = 10
CONNECT_TIMEOUT = 6
RETRY_STATUS = {400, 401, 403, 404, 408, 409, 429, 500, 502, 503, 504}
SCOREBOARD_RETRY_S = [0, 2, 5, 10]            # quick backoff for scoreboard
SUMMARY_RETRY_S    = [0, 2, 5, 10]            # quick backoff for summary/WP

# ESPN URL pieces
SPORT_PATH = {
    "NBA": "basketball/nba",
    "NFL": "football/nfl",
    "MLB": "baseball/mlb",
    # When you’re ready later:
    "NCAAM": "basketball/mens-college-basketball",
    "NCAAF": "football/college-football",
}

# Treat these as national if present in geoBroadcasts/broadcasts
NATIONAL_NETWORKS = {
    # Common
    "ABC", "NBC", "CBS", "FOX", "FS1", "FS2", "TBS", "TNT", "TRU", "TRUTV",
    "ESPN", "ESPN2", "ESPNU", "ESPNEWS", "NBATV", "MLBN", "NFLN",
    # Streamers
    "PEACOCK", "APPLE TV+", "APPLETV+", "PRIME VIDEO", "AMAZON PRIME",
    "AMAZON", "YOUTUBE TV", "YOUTUBE",
    # Variants
    "CBS SPORTS NETWORK", "CBSSN", "SEC NETWORK", "SECN", "BIG TEN NETWORK", "BTN",
    "ACC NETWORK", "ACCN", "LONGHORN NETWORK", "LHN",
}

# Normalize a few broadcaster name quirks
BROADCAST_NORMALIZE = {
    "FS1": "FS1",
    "FS2": "FS2",
    "CBSSN": "CBS Sports Network",
    "SECN": "SEC Network",
    "BTN": "Big Ten Network",
    "ACCN": "ACC Network",
    "TRU": "truTV",
    "TRUTV": "truTV",
    "YOUTUBE": "YouTube",
    "YOUTUBE TV": "YouTube",
    "APPLETV+": "Apple TV+",
    "APPLE TV+": "Apple TV+",
    "PRIME": "Prime Video",
    "AMAZON": "Prime Video",
    "AMAZON PRIME": "Prime Video",
    "PRIME VIDEO": "Prime Video",
    "PEACOCK": "Peacock",
    "CBS SPORTS NETWORK": "CBS Sports Network",
}

# ---------- Session with browser-y headers ----------
_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
    "Cache-Control": "no-cache",
})

def _get(url: str) -> Optional[Dict[str, Any]]:
    """GET with small retry/backoff for ESPN."""
    for i, _ in enumerate(SCOREBOARD_RETRY_S):
        try:
            r = _session.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            if r.status_code == 200:
                return r.json()
            if r.status_code in RETRY_STATUS and i < len(SCOREBOARD_RETRY_S) - 1:
                time.sleep(SCOREBOARD_RETRY_S[i+1])
                continue
            print(f"[DEBUG] GET {url} -> {r.status_code}", flush=True)
            return None
        except requests.RequestException as e:
            if i < len(SCOREBOARD_RETRY_S) - 1:
                time.sleep(SCOREBOARD_RETRY_S[i+1])
                continue
            print(f"[DEBUG] GET {url} exception: {e}", flush=True)
            return None
    return None

def _get_summary(url: str) -> Optional[Dict[str, Any]]:
    """GET for summary/WP with its own backoff."""
    for i, _ in enumerate(SUMMARY_RETRY_S):
        try:
            r = _session.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            if r.status_code == 200:
                return r.json()
            if r.status_code in RETRY_STATUS and i < len(SUMMARY_RETRY_S) - 1:
                time.sleep(SUMMARY_RETRY_S[i+1])
                continue
            print(f"[DEBUG] SUMMARY GET {url} -> {r.status_code}", flush=True)
            return None
        except requests.RequestException as e:
            if i < len(SUMMARY_RETRY_S) - 1:
                time.sleep(SUMMARY_RETRY_S[i+1])
                continue
            print(f"[DEBUG] SUMMARY GET {url} exception: {e}", flush=True)
            return None
    return None

def _yyyymmdd(date_iso: str) -> str:
    # date_iso expected 'YYYY-MM-DD'
    return date_iso.replace("-", "")

def _is_final(comp: Dict[str, Any]) -> bool:
    """ESPN 'Final' detection."""
    st = comp.get("status") or {}
    t = (st.get("type") or {})
    # Either explicitly completed or the state says post
    return bool(t.get("completed")) or (t.get("state", "").lower() == "post")

def _pick_network(game: Dict[str, Any]) -> Optional[str]:
    """Pick a national broadcaster if present."""
    broadcasts = []
    comps = game.get("competitions") or []
    if comps:
        c0 = comps[0]
        # ESPN sometimes puts field in 'broadcasts', sometimes 'geoBroadcasts'
        broadcasts = (c0.get("geoBroadcasts") or c0.get("broadcasts") or [])
    for b in broadcasts:
        # Try various fields
        name = (b.get("media", {}) or {}).get("shortName") or b.get("shortName") or b.get("name") or ""
        market = (b.get("market") or "").upper()
        chan = (b.get("channel") or "").upper()

        guess = (name or chan).strip().upper()
        if guess in BROADCAST_NORMALIZE:
            nice = BROADCAST_NORMALIZE[guess]
        else:
            nice = name.strip() or chan.title()

        # national test
        if market == "NATIONAL" or guess in NATIONAL_NETWORKS:
            return nice or None
    return None

def _home_away_names(game: Dict[str, Any]) -> Tuple[str, str]:
    """Return (away, home) display names."""
    comps = game.get("competitions") or []
    if not comps:
        return "", ""
    c0 = comps[0]
    aw = ho = ""
    for comp in (c0.get("competitors") or []):
        team = (comp.get("team") or {})
        name = team.get("shortDisplayName") or team.get("displayName") or team.get("name") or team.get("shortName") or ""
        if comp.get("homeAway") == "home":
            ho = name
        else:
            aw = name
    return aw, ho

def _neutral_site(game: Dict[str, Any]) -> bool:
    comps = game.get("competitions") or []
    if not comps:
        return False
    return bool(comps[0].get("neutralSite", False))

def _event_name(game: Dict[str, Any]) -> Optional[str]:
    # Pull an event/tournament label if present; safe to be None
    comps = game.get("competitions") or []
    if not comps:
        return None
    notes = comps[0].get("notes") or []
    for n in notes:
        if (n.get("type") or "").lower() in {"event", "tournament", "vitals"}:
            txt = (n.get("headline") or n.get("text") or "").strip()
            if txt:
                return txt
    # Some sports include it at top-level
    return (game.get("name") or "").strip() or None

def _extract_ids(game: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Return (event_id, competition_id)."""
    event_id = str(game.get("id") or "")
    comp_id = None
    comps = game.get("competitions") or []
    if comps:
        comp_id = str(comps[0].get("id") or "")
    return event_id or None, comp_id or None

# ---------- Public: scoreboard fetch ----------
def list_final_events_for_date(date_iso: str, leagues: List[str]) -> List[Dict[str, Any]]:
    """
    Return list of final events for the given ISO date across requested leagues.
    Each item includes: sport, road, home, network, neutral_site, event_name, event_id, comp_id
    """
    results: List[Dict[str, Any]] = []
    ymd = _yyyymmdd(date_iso)

    for league in leagues:
        path = SPORT_PATH.get(league)
        if not path:
            continue
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={ymd}"

        data = _get(url)
        if not data:
            print(f"[DEBUG] scoreboard load failed for {league}", flush=True)
            continue

        events = data.get("events") or []
        finals_like = 0
        for g in events:
            comps = g.get("competitions") or []
            if not comps:
                continue
            if not _is_final(comps[0]):
                continue

            finals_like += 1
            away, home = _home_away_names(g)
            network = _pick_network(g)
            neutral = _neutral_site(g)
            event_label = _event_name(g)
            ev_id, comp_id = _extract_ids(g)

            results.append({
                "sport": league,
                "road": away,
                "home": home,
                "network": network,           # None if not clearly national
                "neutral_site": neutral,
                "event_name": event_label,
                "event_id": ev_id,
                "comp_id": comp_id,
            })

        print(f"[DEBUG] {league} events={len(events)}", flush=True)
        print(f"[DEBUG] {league} finals_like={finals_like}", flush=True)

    print(f"[INFO] {date_iso} FINAL-like events found: {len(results)}", flush=True)
    return results

# ---------- Public: WP series fetch ----------
def fetch_win_probability_series(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    """
    Return a list of home-team win probability (0..1) over time.
    Tries multiple endpoints:
      1) sports.core.api winprobability
      2) site.api summary?event=
    """
    path = SPORT_PATH.get(sport.upper())
    if not path:
        return None

    # 1) Core API winprobability (most direct when available)
    #    Example:
    #    https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{event_id}/competitions/{comp_id}/probabilities
    core_url = f"https://sports.core.api.espn.com/v2/sports/{path}/events/{event_id}/competitions/{comp_id}/probabilities"
    core = _get_summary(core_url)
    series = _parse_wp_core(core)
    if series:
        return series

    # 2) Site summary fallback (commonly has winprobability array)
    #    https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={event_id}
    sum_url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={event_id}"
    summ = _get_summary(sum_url)
    series = _parse_wp_summary(summ)
    if series:
        return series

    print(f"[DEBUG] WP series not found for {sport} evt={event_id}/{comp_id}", flush=True)
    return None

# ---------- Parsers ----------
def _parse_wp_core(payload: Optional[Dict[str, Any]]) -> Optional[List[float]]:
    if not payload:
        return None
    # Core format: {"items":[{"homeWinPercentage": 63.2, ...}, ...]}
    items = payload.get("items") or []
    if not items:
        return None
    out: List[float] = []
    for it in items:
        # ESPN sometimes uses 0..1 or 0..100. Try both safely.
        p = it.get("homeWinPercentage")
        if p is None:
            continue
        try:
            p = float(p)
            if p > 1.001:  # looks like percent
                p = p / 100.0
            out.append(max(0.0, min(1.0, p)))
        except Exception:
            continue
    return out or None

def _parse_wp_summary(payload: Optional[Dict[str, Any]]) -> Optional[List[float]]:
    if not payload:
        return None
    # Site summary format: {"winprobability":[{"homeWinPercentage":0.532}, ...]}
    wps = payload.get("winprobability") or payload.get("winProbability") or []
    if not wps:
        # Some sports place under competitions[0].probabilities
        comps = payload.get("competitions") or []
        if comps and isinstance(comps, list):
            probs = comps[0].get("probabilities") or []
            wps = probs

    if not wps:
        return None

    out: List[float] = []
    for it in wps:
        p = it.get("homeWinPercentage") or it.get("homeWinProb")
        if p is None:
            continue
        try:
            p = float(p)
            if p > 1.001:
                p = p / 100.0
            out.append(max(0.0, min(1.0, p)))
        except Exception:
            continue
    return out or None

