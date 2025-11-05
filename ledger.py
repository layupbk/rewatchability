# ledger.py
import os, json
from datetime import datetime, timedelta, timezone

# Where to store the ledger file (on your Render disk)
LEDGER_PATH = os.getenv("LEDGER_PATH", "/data/posted_ledger.json")
# How long to remember posted games (days)
LEDGER_DAYS = int(os.getenv("LEDGER_DAYS", "7"))

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_ledger() -> dict[str, str]:
    """Return {event_id: iso_timestamp}."""
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                # Ensure keys/values are strings
                return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[LEDGER] load error: {e}", flush=True)
    return {}

def save_ledger(ledger: dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "w", encoding="utf-8") as f:
            json.dump(ledger, f)
        print(f"[LEDGER] saved {len(ledger)} ids to {LEDGER_PATH}", flush=True)
    except Exception as e:
        print(f"[LEDGER] save error: {e}", flush=True)

def prune_ledger(ledger: dict[str, str], days: int = LEDGER_DAYS) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keep: dict[str, str] = {}
    removed = 0
    for eid, ts in ledger.items():
        try:
            when = datetime.fromisoformat(ts)
        except Exception:
            removed += 1
            continue
        if when >= cutoff:
            keep[eid] = ts
        else:
            removed += 1
    if removed:
        print(f"[LEDGER] pruned {removed} old ids (> {days} days)", flush=True)
    ledger.clear()
    ledger.update(keep)

def already_posted(ledger: dict[str, str], event_id: str) -> bool:
    return event_id in ledger

def mark_posted(ledger: dict[str, str], event_id: str) -> None:
    ledger[event_id] = _now_iso()
