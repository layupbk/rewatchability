# espn_adapter.py
import requests
from typing import List, Dict, Optional

# ------------------------------
# Helpers
# ------------------------------

SPORT_PATH = {
    "NBA": "basketball/nba",
    "NFL": "football/nfl",
    "MLB": "baseball/mlb",
}

def _http_get_json(url: str, timeout: int = 10):
    r = requests.get(url, timeout=timeout)
    if r.status_code != 200:
        print(f"[DEBUG] GET {url} -> {r.status_code}", flush=True)
        return None
    try:
        return r.json()
    except Exception as e:
        print(f"[DEBUG] JSON parse error for {url}: {e}", flush=True)
        return None

def _is_final_like(event: dict) -> bool:
    """
    ESPN events have status info in a few places. We accept:
    - status.type.completed == True
    - status.type.state == 'post'
    - shortText contains 'Final'
    """
    try:
        stat = event.get("status") or {}
        stype = stat.get("type") or {}
        if stype.get("completed") is True:
            return True
        if (stype.get("state") or "").lower() == "post":
            return True
        if "final" in (stat.get("type", {}).get("shortDetail", "") or "").lower():
            return True
        if "final" in (stat.get("type", {}).get("description", "") or "").lower():
            return True
    except Exception:
        pass
    return False

def _extract_competitors(event: dict):
    """
    Return (road_name, home_name, neutral_site_bool, comp_id) from the first competition.
    """
    comps = (event.get("competitions") or [])
    if not comps:
        return None, None, False, None
    comp0 = comps[0]
    comp_id = str(comp0.get("id") or "")
    neutral = bool(comp0.get("neutralSite") or False)

    road = home = None
    for c in comp0.get("competitors", []):
        name = (c.get("team", {}) or {}).get("displayName") or (c.get("team", {}) or {}).get("name")
        ha = c.get("homeAway")
        if ha == "home":
            home = name
        elif ha == "away":
            road = name

    return road, home, neutral, comp_id

def _extract_event_name(event: dict) -> Optional[str]:
    """
    Try a few places for an event/tournament name if present.
    """
    # Sometimes on pro side there isn't a special name; return None if nothing meaningful.
    header_name = (event.get("name") or "").strip()
    if header_name:
        # Often "Lakers vs. Warriors" (not useful). Skip if it just mirrors teams.
        if " vs " in header_name.lower() or " vs. " in header_name.lower() or " at " in header_name.lower():
            pass
        else:
            return header_name

    # Competitions notes/title
    comps = event.get("competitions") or []
    if comps:
        notes = comps[0].get("notes") or []
        for n in notes:
            txt = (n.get("headline") or "").strip()
            if txt:
                return txt

    return None

def _extract_network_national(event: dict) -> Optional[str]:
    """
    Return a national network string like "ABC", "ESPN", "TNT", "FOX", "CBS", "NBC/Peacock", etc.
    If not national, return None.
    """
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp0 = comps[0]

    # ESPN puts broadcasts under competitions[0].broadcasts
    broadcasts = comp0.get("broadcasts") or []
    # Look for items where market == 'national'
    national_names = []
    for b in broadcasts:
        market = (b.get("market") or "").lower()
        names = b.get("names") or []
        if market == "national" and names:
            # Some events list multiple names, e.g., ["NBC", "Peacock"]
            national_names.extend([str(n) for n in names if n])

    if not national_names:
        return None

    # Deduplicate while preserving order
    seen = set()
    uniq = []
    for n in national_names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)

    # Join multiple (e.g., NBC/Peacock)
    return "/".join(uniq)

# ------------------------------
# Public: list events for a date
# ------------------------------

def list_final_events_for_date(date_iso: str, leagues: List[str]) -> List[Dict]:
    """
    For the given yyyy-mm-dd date, pull FINAL-like events for the requested leagues.
    Return list of dicts with:
      sport, road, home, network, neutral_site, event_name, event_id, comp_id
    """
    out: List[Dict] = []
    for league in leagues:
        sport_path = SPORT_PATH.get(league.upper())
        if not sport_path:
            continue

        # ESPN Scoreboard
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_iso}"
        data = _http_get_json(url)
        if not data:
            continue

        events = data.get("events") or []
        finals = 0
        for ev in events:
            if not _is_final_like(ev):
                continue

            event_id = str(ev.get("id") or "")
            road, home, neutral, comp_id = _extract_competitors(ev)
            if not (event_id and road and home and comp_id):
                continue

            network = _extract_network_national(ev)  # None if non-national
            event_name = _extract_event_name(ev)     # may be None

            out.append({
                "sport": league.upper(),
                "road": road,
                "home": home,
                "network": network,
                "neutral_site": neutral,
                "event_name": event_name,
                "event_id": event_id,
                "comp_id": comp_id,
            })
            finals += 1

        print(f"[DEBUG] {league} events={len(events)}", flush=True)
        print(f"[DEBUG] {league} finals_like={finals}", flush=True)

    return out

# ------------------------------
# Public: Win Probability series
# ------------------------------

def fetch_win_probability_series(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    """
    Return a list of HOME win probabilities (floats 0..1) in time order.
    Strategy:
      1) Try a primary fetch (stubbed here; return None to fall back).
      2) Fallback to ESPN 'summary?event=' which usually exposes 'winprobability'.
    """
    # 1) Primary (if you later wire a direct endpoint, do it here)
    try:
        primary = _fetch_wp_primary(sport, event_id, comp_id)
        if primary and len(primary) >= 2:
            print(f"[DEBUG] WP primary ok: {event_id}", flush=True)
            return primary
    except Exception as e:
        print(f"[DEBUG] WP primary error {event_id}: {e}", flush=True)

    # 2) Fallback: ESPN summary
    try:
        sport_path = SPORT_PATH.get(sport.upper())
        if not sport_path:
            return None

        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={event_id}"
        data = _http_get_json(url, timeout=8)
        if not data:
            print(f"[DEBUG] summary load failed for {event_id}", flush=True)
            return None

        # Identify home team id if needed (usually not required because percentages are explicit)
        home_team_id = None
        try:
            comps = data.get("header", {}).get("competitions") or data.get("competitions") or []
            if comps:
                comp0 = comps[0]
                for c in comp0.get("competitors", []):
                    if c.get("homeAway") == "home":
                        home_team_id = str(c.get("id") or c.get("team", {}).get("id") or "")
                        break
        except Exception:
            pass

        wp_list = data.get("winprobability")
        if not isinstance(wp_list, list) or len(wp_list) < 2:
            print(f"[DEBUG] no winprobability in summary for {event_id}", flush=True)
            return None

        home_series: List[float] = []
        for pt in wp_list:
            if "homeWinPercentage" in pt:
                try:
                    home_series.append(float(pt["homeWinPercentage"]))
                    continue
                except Exception:
                    pass
            if "awayWinPercentage" in pt:
                try:
                    aw = float(pt["awayWinPercentage"])
                    home_series.append(max(0.0, min(1.0, 1.0 - aw)))
                    continue
                except Exception:
                    pass
            # If neither present (rare), skip that point.

        if len(home_series) >= 2:
            print(f"[DEBUG] WP fallback ok: {event_id} points={len(home_series)}", flush=True)
            return home_series

        print(f"[DEBUG] fallback parsed but too short for {event_id}", flush=True)
        return None

    except Exception as e:
        print(f"[DEBUG] WP fallback error {event_id}: {e}", flush=True)
        return None

def _fetch_wp_primary(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    """
    Stub for a direct probabilities endpoint if you add one later.
    Returning None makes the fallback run immediately.
    """
    return None

