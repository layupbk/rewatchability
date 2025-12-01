# inpredictable.py
#
# Fetches Excitement Index (EI) from Inpredictable's PreCap page and returns
# a mapping keyed by ESPN-style team abbreviations.
#
# Supports: NBA PreCap via stats.inpredictable.com
# WNBA: returns an empty map for now (no official PreCap).

from __future__ import annotations

import re
import time
from typing import Dict, Tuple

import requests

# Official PreCap page for yesterday's NBA games.
# (This page always shows the most recent completed NBA slate.)
NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCapOld.php"

# If/when you add WNBA support, you can point this at a WNBA PreCap equivalent.
WNBA_PRECAP_URL = None  # placeholder

# Simple in-memory cache so we don't hammer Inpredictable unnecessarily
_CACHE: Dict[str, Dict[Tuple[str, str], float]] = {}
_CACHE_TS: Dict[str, float] = {}
_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes


def _log(msg: str) -> None:
    print(f"[INPRED] {msg}", flush=True)


def _fetch_raw_html(url: str) -> str:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


def _extract_main_table(html: str) -> str:
    """
    The PreCap page has a TON of Blogger/JS noise. We only want the chunk
    between the 'Rank Game Status Excitement...' header and 'League Averages'.
    This also avoids bogus matches like 'SON @ ONE' in script tags.
    """
    header = "Rank Game Status Excitement"
    footer = "League Averages"

    start = html.find(header)
    if start == -1:
        _log("could not locate PreCap table header")
        return ""

    end = html.find(footer, start)
    if end == -1:
        end = len(html)

    return html[start:end]


def _parse_pre_cap_table(league: str, html: str) -> Dict[Tuple[str, str], float]:
    """
    Parse the PreCap table and return a mapping:
        (AWAY_ESPN_ABBR, HOME_ESPN_ABBR) -> excitement (float)
    """
    table = _extract_main_table(html)
    if not table:
        return {}

    _log(f"PreCap text length = {len(html)} chars")

    # Pattern (within the table chunk) looks roughly like:
    #   1  ATL @ PHI  ... Finished 13.7  82% ...
    row_pattern = re.compile(
        r"\b\d+\s*([A-Z]{2,3})\s*@\s*([A-Z]{2,3}).*?Finished\s+([\d.]+)",
        re.DOTALL,
    )

    results: Dict[Tuple[str, str], float] = {}

    for match in row_pattern.finditer(table):
        away_abbr_raw, home_abbr_raw, ei_str = match.groups()
        away_pre = away_abbr_raw.strip()
        home_pre = home_abbr_raw.strip()

        try:
            excitement = float(ei_str)
        except ValueError:
            continue

        # In NBA, Inpredictable and ESPN abbreviations generally match.
        # For WNBA, you'd add mapping here if/when you parse WNBA PreCap.
        away_espn = _normalize_abbr(league, away_pre)
        home_espn = _normalize_abbr(league, home_pre)

        results[(away_espn, home_espn)] = excitement

        # Keep logging tiny & readable (no giant HTML dump).
        _log(f"ROW parsed: {away_espn} @ {home_espn} -> Excitement {excitement}")

    _log(f"parsed {len(results)} finished games from PreCap for {league}")
    return results


def _normalize_abbr(league: str, abbr: str) -> str:
    """
    Map Inpredictable's team abbreviation to the ESPN abbreviation that
    the scoreboard uses. For NBA they already match; for WNBA there are
    known differences (NYL vs NY, LVA vs LV, etc.) if/when you wire it up.
    """
    league = league.upper()

    if league == "WNBA":
        # When you add WNBA PreCap parsing, fill this out, e.g.:
        # mapping = {
        #     "NYL": "NY",   # Liberty
        #     "LVA": "LV",   # Aces
        #     "LAS": "LA",   # Sparks
        # }
        mapping = {}
        return mapping.get(abbr, abbr)

    # Default: NBA – already aligned
    return abbr


def _get_cache_key(league: str) -> str:
    # For now, PreCapOld is "yesterday's games", so we just cache by league.
    return league.upper()


def _get_from_cache(league: str) -> Dict[Tuple[str, str], float] | None:
    key = _get_cache_key(league)
    ts = _CACHE_TS.get(key)
    if ts is None:
        return None
    if time.time() - ts > _CACHE_TTL_SECONDS:
        return None
    return _CACHE.get(key)


def _set_cache(league: str, mapping: Dict[Tuple[str, str], float]) -> None:
    key = _get_cache_key(league)
    _CACHE[key] = mapping
    _CACHE_TS[key] = time.time()


def fetch_excitement_map(league: str) -> Dict[Tuple[str, str], float]:
    """
    Public entry point.

    Returns:
        dict keyed by (AWAY_ESPN_ABBR, HOME_ESPN_ABBR) -> excitement float

    NOTE: This intentionally ignores the date argument that used to exist.
    PreCapOld always shows the most recent complete slate (i.e., "yesterday"),
    which matches how the autopilot uses it.
    """
    league_up = league.upper()

    # Cache hit?
    cached = _get_from_cache(league_up)
    if cached is not None:
        return cached

    if league_up == "NBA":
        url = NBA_PRECAP_URL
    elif league_up == "WNBA":
        # No WNBA PreCap yet – just return an empty mapping.
        _log("WNBA PreCap not configured; returning empty map.")
        _set_cache(league_up, {})
        return {}
    else:
        _log(f"Unsupported league for PreCap: {league_up}")
        _set_cache(league_up, {})
        return {}

    _log(f"fetching PreCap for {league_up} via {url}")

    try:
        html = _fetch_raw_html(url)
        mapping = _parse_pre_cap_table(league_up, html)
        _set_cache(league_up, mapping)
        return mapping
    except Exception as ex:
        _log(f"ERROR fetching PreCap for {league_up}: {ex}")
        # If we have a stale cache, prefer that to total failure
        stale = _CACHE.get(_get_cache_key(league_up))
        if stale:
            _log(f"using stale cached PreCap for {league_up}")
            return stale
        return {}
