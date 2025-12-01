# inpredictable.py
# Scraper for inpredictable.com's PreCap "Excitement" tables.
#
# Supports:
#   - NBA  -> https://stats.inpredictable.com/nba/preCap.php
#   - WNBA -> https://stats.inpredictable.com/wnba/preCap.php
#
# Public API:
#   fetch_excitement_map("NBA")  -> dict[(away_abbrev, home_abbrev), excitement_float]
#   fetch_excitement_map("WNBA") -> same, for WNBA

from __future__ import annotations

import re
import time
from typing import Dict, Tuple, Optional

import requests

NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCap.php"
WNBA_PRECAP_URL = "https://stats.inpredictable.com/wnba/preCap.php"

PRECAP_URLS = {
    "NBA": NBA_PRECAP_URL,
    "WNBA": WNBA_PRECAP_URL,
}

# Parse strings like "DET @ BOS" (possibly with extra junk after them)
GAME_CELL_RE = re.compile(
    r"""
    ^\s*
    (?P<away>[A-Z]{2,4})      # away team abbreviation
    \s*@\s*
    (?P<home>[A-Z]{2,4})      # home team abbreviation
    """,
    re.VERBOSE,
)

# Simple in-process cache:
#   league -> {"ts": float, "mapping": dict[(away,home)->float]}
_CACHE: Dict[str, Dict[str, object]] = {}
CACHE_TTL_SECONDS = 120.0  # okay to re-use for a couple of minutes


def _log(msg: str) -> None:
    print(f"[INPRED] {msg}", flush=True)


def _fetch_precap_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            _log(f"GET {url} -> {resp.status_code}")
            return None
        resp.encoding = "utf-8"
        return resp.text
    except Exception as ex:
        _log(f"error fetching {url}: {ex}")
        return None


def _parse_precap_table(html: str) -> Dict[Tuple[str, str], float]:
    """
    Return {(away_abbr, home_abbr): excitement_float} for games
    where Status == "Finished".
    """
    rows: Dict[Tuple[str, str], float] = {}

    # Normalize line breaks
    cleaned = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)

    # Find the header row that introduces Rank/Game/Status/Excitement/Tension
    header_match = re.search(
        r"Rank\s*Game\s*Status\s*Excitement\s*Tension",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not header_match:
        return rows

    table_text = cleaned[header_match.end() :]

    # Each row roughly: rank, game, status, excitement, tension, ...
    game_pattern = re.compile(
        r"""
        (?P<rank>\d+)
        \s+
        (?P<game>[A-Z]{2,4}\s*@\s*[A-Z]{2,4}[^0-9\n]*?)
        \s+
        (?P<status>Finished|In\ Progress|Scheduled)
        \s+
        (?P<excite>\d+(\.\d+)?)
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    for m in game_pattern.finditer(table_text):
        status = m.group("status").strip().lower()
        if status != "finished":
            continue

        game_cell = m.group("game")
        excite_str = m.group("excite")

        if not excite_str:
            continue

        gm = GAME_CELL_RE.search(game_cell)
        if not gm:
            continue
        away = gm.group("away").upper()
        home = gm.group("home").upper()

        try:
            excite = float(excite_str)
        except ValueError:
            continue

        rows[(away, home)] = excite

    return rows


def _get_cached_mapping(league_up: str) -> Optional[Dict[Tuple[str, str], float]]:
    entry = _CACHE.get(league_up)
    if not entry:
        return None
    ts = entry.get("ts")
    mapping = entry.get("mapping")
    if not isinstance(mapping, dict) or not isinstance(ts, (int, float)):
        return None
    if (time.time() - ts) > CACHE_TTL_SECONDS:
        return None
    return mapping  # still fresh


def _set_cached_mapping(league_up: str, mapping: Dict[Tuple[str, str], float]) -> None:
    _CACHE[league_up] = {"ts": time.time(), "mapping": mapping}


def fetch_excitement_map(league: str) -> Dict[Tuple[str, str], float]:
    """
    Return a dict mapping (away_abbr, home_abbr) -> inpredictable Excitement (raw).

    Behavior:
      - Try to fetch and parse the current PreCap page.
      - If it yields a non-empty mapping, cache it and return.
      - If it fails or parses to empty, fall back to a recent cached mapping
        (if available) instead of returning {}.
    """
    league_up = (league or "").upper()
    if league_up not in PRECAP_URLS:
        raise ValueError(f"Unsupported league for inpredictable PreCap: {league!r}")

    url = PRECAP_URLS[league_up]

    html = _fetch_precap_html(url)
    if html:
        mapping = _parse_precap_table(html)
        if mapping:
            _set_cached_mapping(league_up, mapping)
            _log(f"parsed {len(mapping)} finished games from PreCap for {league_up}")
            return mapping
        else:
            _log(f"parsed 0 finished games from PreCap for {league_up}")
    else:
        _log(f"no HTML from PreCap for {league_up}")

    # Fallback: use cached mapping if available
    cached = _get_cached_mapping(league_up)
    if cached:
        _log(
            f"using cached Excitement mapping for {league_up} "
            f"(len={len(cached)})"
        )
        return cached

    # Nothing available
    _log(f"no Excitement data available (live or cache) for {league_up}")
    return {}
