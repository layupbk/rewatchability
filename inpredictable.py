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
from typing import Dict, Tuple

import requests

NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCap.php"
WNBA_PRECAP_URL = "https://stats.inpredictable.com/wnba/preCap.php"

PRECAP_URLS = {
    "NBA": NBA_PRECAP_URL,
    "WNBA": WNBA_PRECAP_URL,
}


def _fetch_precap_html(url: str, attempts: int = 3, timeout: int = 20) -> str | None:
    """
    Fetch the raw HTML for a PreCap page, with retries.

    - attempts: how many times to retry on network/timeout errors.
    - timeout: seconds per individual HTTP request.
    """
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code != 200:
                print(
                    f"[INPRED] GET {url} -> {resp.status_code} on attempt "
                    f"{attempt}/{attempts}",
                    flush=True,
                )
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
            else:
                resp.encoding = "utf-8"
                return resp.text
        except Exception as ex:
            last_exc = ex
            print(
                f"[INPRED] error fetching {url} on attempt "
                f"{attempt}/{attempts}: {ex}",
                flush=True,
            )

        if attempt < attempts:
            time.sleep(3)  # brief pause before trying again

    print(
        f"[INPRED] giving up after {attempts} attempts for {url}: {last_exc}",
        flush=True,
    )
    return None


def _parse_precap_table(html: str) -> Dict[Tuple[str, str], float]:
    """
    Return {(away_abbr, home_abbr): excitement_float} for games
    where Status == "Finished".

    We first strip HTML tags down to plain text so the regex works
    reliably even if there are links, images, etc. in the Game column.
    """
    rows: Dict[Tuple[str, str], float] = {}

    # 1) Normalize <br> tags to spaces
    text = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)

    # 2) Strip ALL other HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # 3) Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Find the header row that starts the main table
    header_match = re.search(
        r"Rank\s+Game\s+Status\s+Excitement\s+Tension",
        text,
        flags=re.IGNORECASE,
    )
    if not header_match:
        return rows

    table_text = text[header_match.end() :]

    # Example line (after stripping tags & collapsing spaces):
    # "1 ATL @ PHI Finished 13.7 82% 38.1 +65.0%"
    #
    # Sometimes there may be an "Image" token or similar between the
    # game and the status, so we allow one optional word there.
    game_pattern = re.compile(
        r"(?P<rank>\d+)\s+"
        r"(?P<away>[A-Z]{2,4})\s*@\s*(?P<home>[A-Z]{2,4})\s+"
        r"(?:\S+\s+)?"
        r"(?P<status>Finished|In Progress|Scheduled)\s+"
        r"(?P<excite>\d+(\.\d+)?)",
        re.IGNORECASE,
    )

    for m in game_pattern.finditer(table_text):
        status = m.group("status").strip().lower()
        if status != "finished":
            continue

        away = m.group("away").upper()
        home = m.group("home").upper()

        excite_str = m.group("excite")
        try:
            excite = float(excite_str)
        except (TypeError, ValueError):
            continue

        rows[(away, home)] = excite

    return rows


def fetch_excitement_map(league: str) -> Dict[Tuple[str, str], float]:
    """
    Return a dict mapping (away_abbr, home_abbr) -> inpredictable Excitement (raw).
    """
    league_up = (league or "").upper()
    if league_up not in PRECAP_URLS:
        raise ValueError(f"Unsupported league for inpredictable PreCap: {league!r}")

    url = PRECAP_URLS[league_up]
    html = _fetch_precap_html(url)
    if not html:
        # We already logged why it failed; return empty so caller can "WAIT".
        return {}

    mapping = _parse_precap_table(html)
    print(
        f"[INPRED] parsed {len(mapping)} finished games from PreCap for {league_up}",
        flush=True,
    )
    return mapping
