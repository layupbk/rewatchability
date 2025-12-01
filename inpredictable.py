# inpredictable.py
# Scraper for inpredictable.com's PreCap "Excitement" tables, with per-date caching.
#
# Supports:
#   - NBA  -> https://stats.inpredictable.com/nba/preCap.php
#   - WNBA -> https://stats.inpredictable.com/wnba/preCap.php
#
# Public API:
#   fetch_excitement_map("NBA",  "2025-11-30")
#   fetch_excitement_map("WNBA", "2025-11-30")
#
# Returns:
#   dict[(away_abbrev, home_abbrev), excitement_float]

from __future__ import annotations

import re
import datetime
from typing import Dict, Tuple, Optional

import requests

NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCap.php"
WNBA_PRECAP_URL = "https://stats.inpredictable.com/wnba/preCap.php"

PRECAP_URLS: Dict[str, str] = {
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

# Per-(league, date_iso) cache: (league_up, date_iso) -> {"mapping": dict, "fetched_at": datetime}
_CACHE: Dict[Tuple[str, str], Dict[str, object]] = {}


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

    # Normalize <br> variations to spaces for easier regex parsing.
    cleaned = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)

    # Anchor around the header line.
    header_match = re.search(
        r"Rank\s*Game\s*Status\s*Excitement\s*Tension",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not header_match:
        return rows

    table_text = cleaned[header_match.end() :]

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
            # We only want completed games for EI.
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


def fetch_excitement_map(league: str, date_iso: str) -> Dict[Tuple[str, str], float]:
    """
    Return a dict mapping (away_abbr, home_abbr) -> inpredictable Excitement (raw),
    with per-(league, date_iso) caching.

    Behavior:
      - Try to pull the PreCap page and parse it.
      - If we get a non-empty mapping, we cache and return it.
      - If the fetch fails OR parses to zero finished games, we fall back to
        the last cached mapping for that (league, date_iso) if it exists.
      - Otherwise we return {}.
    """
    league_up = (league or "").upper()
    if league_up not in PRECAP_URLS:
        raise ValueError(f"Unsupported league for inpredictable PreCap: {league!r}")

    cache_key = (league_up, date_iso)
    url = PRECAP_URLS[league_up]

    html = _fetch_precap_html(url)
    if html:
        mapping = _parse_precap_table(html)
        if mapping:
            _CACHE[cache_key] = {
                "mapping": mapping,
                "fetched_at": datetime.datetime.utcnow(),
            }
            _log(
                f"parsed {len(mapping)} finished games from PreCap for {league_up} "
                f"({date_iso})"
            )
            return mapping
        else:
            _log(
                f"parsed 0 finished games from PreCap for {league_up} ({date_iso}); "
                "will try cache if available."
            )
    else:
        _log(
            f"no HTML from PreCap for {league_up} ({date_iso}); "
            "will try cache if available."
        )

    # Fallback to cache for this league+date if we have one
    cached = _CACHE.get(cache_key)
    if cached and isinstance(cached.get("mapping"), dict):
        mapping = cached["mapping"]  # type: ignore[assignment]
        _log(
            f"using cached mapping with {len(mapping)} games for {league_up} "
            f"({date_iso})"
        )
        return mapping  # type: ignore[return-value]

    # No data from HTML and no cache.
    _log(f"no PreCap data or cache for {league_up} ({date_iso})")
    return {}
