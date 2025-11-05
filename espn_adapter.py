# espn_adapter.py
# Pull FINAL (or immediate post-game) games + win probabilities from ESPN.

from typing import List, Dict, Any, Optional
import requests
import re

SPORT_PATH = {
    "NBA":   ("basketball", "nba"),
    "NFL":   ("football", "nfl"),
    "MLB":   ("baseball", "mlb"),
    "NCAAM": ("basketball", "mens-college-basketball"),
    "NCAAF": ("football", "college-football"),
}

def _to_yyyymmdd(d: str) -> str:
    d = (d or "").strip()
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d.replace("-", "")
    return d

def _get_json(url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None

def _scoreboard_url(group: str, league: str, date_param: str) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/{group}/{league}/scoreboard?dates={date_param}"

def _looks_final(status_type: Dict[str, Any]) -> bool:
    """
    Consider the game 'final' if ESPN says it's completed OR in post-game state,
    or if the status name is clearly a final/full-time marker.
    """
    if not status_type:
        return False
    if status_type.get("completed"):
        return True
    state = (status_type.get("state") or "").lower()      # e.g., 'pre', 'in', 'post'
    if state == "post":
        return True
    name = (status_type.get("name") or "").upper()
    if name in {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_END"}:
        return True
    return False

def list_final_events_for_date(date_str: str, leagues: List[str]) -> List[Dict[str, Any]]:
    """
    Return games that are FINAL or immediately POST-GAME for the date.
    Each item:
      { sport, event_id, comp_id, road, home, network, neutral_site, event_name }
    """
    out: List[Dict[str, Any]] = []
    ymd = _to_yyyymmdd(date_str)
    ymd_dash = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" if len(ymd) == 8 else date_str

    for sport in leagues:
        if sport not in SPORT_PATH:
            continue
        group, league = SPORT_PATH[sport]

        # Try YYYYMMDD first, fallback to dashed
        url1 = _scoreboard_url(group, league, ymd)
        data = _get_json(url1)
        if not data or not data.get("events"):
            url2 = _scoreboard_url(group, league, ymd_dash)
            data = _get_json(url2)

        total = len((data or {}).get("events", [])) if data else 0
        print(f"[DEBUG] {sport} events={total}")

        if not data or not data.get("events"):
            print(f"[DEBUG] {sport} finals=0")
            continue

        finals_count = 0
        for ev in data.get("events", []):
            comps = ev.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]

            stype = (comp.get("status") or {}).get("type") or {}
            if not _looks_final(stype):
                continue

            finals_count += 1

            competitors = comp.get("competitors") or []
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            if not away or not home:
                continue

            def _name(c: Dict[str, Any]) -> str:
                t = c.get("team") or {}
                return t.get("displayName") or t.get("shortDisplayName") or t.get("name") or ""

            road_name = _name(away)
            home_name = _name(home)
            neutral = bool((comp.get("venue") or {}).get("neutralSite"))

            # national broadcast string for headline only
            network_text = None
            for b in (comp.get("broadcasts") or []):
                if (b.get("market") or "").lower() == "national":
                    names = b.get("names") or []
                    if names:
                        network_text = names[0]
                        break

            # event/tournament label for hashtag
            event_name = None
            notes = comp.get("notes") or []
            if isinstance(notes, list) and notes:
                event_name = notes[0].get("headline") or notes[0].get("shortHeadline")
            if not event_name:
                champ = (comp.get("championship") or {}).get("name")
                if champ:
                    event_name = champ
            if not event_name:
                series = (comp.get("series") or {}).get("name")
                if series:
                    event_name = series

            out.append({
                "sport": sport,
                "event_id": ev.get("id"),
                "comp_id": comp.get("id"),
                "road": road_name,
                "home": home_name,
                "network": network_text,
                "neutral_site": neutral,
                "event_name": event_name,
            })

        print(f"[DEBUG] {sport} finals_like={finals_count}")

    return out

def fetch_win_probability_series(sport: str, event_id: str, comp_id: str) -> Optional[List[float]]:
    """
    Return HOME-team win probability series (0..1). If not exposed, return None.
    """
    group, league = SPORT_PATH.get(sport, (None, None))
    if not group:
        return None

    url = f"https://sports.core.api.espn.com/v2/sports/{group}/{league}/events/{event_id}/competitions/{comp_id}/probabilities"
    data = _get_json(url)

    ok = bool(data and data.get("items"))
    print(f"[DEBUG] probs {sport} event={event_id} comp={comp_id} ok={ok}")
    if not ok:
        return None

    probs: List[float] = []
    for it in data.get("items", []):
        val = None
        for key in ("homeTeamOdds", "homeTeamProbability", "homeWinPercentage", "homeWinPercent", "homeWinProb"):
            raw = it.get(key)
            if isinstance(raw, (int, float)):
                val = float(raw); break
            if isinstance(raw, str) and re.match(r"^\d+(\.\d+)?$", raw.strip()):
                val = float(raw); break
        if val is None and isinstance(it.get("homeTeamProbability"), dict):
            v = it["homeTeamProbability"].get("value")
            if isinstance(v, (int, float)):
                val = float(v)
        if val is None:
            continue
        if val > 1.5:
            val = val / 100.0
        probs.append(max(0.0, min(1.0, val)))

    return probs or None
