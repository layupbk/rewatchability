# publisher_x.py
import os
import tweepy
import logging

log = logging.getLogger("publisher_x")
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("X_API_KEY") or os.getenv("TWITTER_API_KEY")
API_SECRET = os.getenv("X_API_SECRET") or os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN") or os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_SECRET = os.getenv("X_ACCESS_SECRET") or os.getenv("TWITTER_ACCESS_SECRET")

def _get_api():
    if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET]):
        log.error("[X] missing one or more credentials")
        return None
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
    api = tweepy.API(auth, wait_on_rate_limit=True)
    try:
        me = api.verify_credentials()
        if me:
            log.info(f"[X] auth OK as @{me.screen_name} (id={me.id})")
        else:
            log.error("[X] verify_credentials returned None")
            return None
    except Exception as e:
        log.error(f"[X] verify_credentials failed: {e}")
        return None
    return api

def post_to_x(text: str) -> bool:
    """
    Returns True only if the tweet was successfully posted.
    Uses the v1.1 statuses/update endpoint via OAuth1 user context.
    """
    api = _get_api()
    if not api:
        return False

    # hard 280 cap for text-only
    status = (text or "")[:280]
    try:
        tw = api.update_status(status=status)
        log.info(f"[X] tweet posted id={tw.id}")
        return True
    except tweepy.errors.Forbidden as e:
        # This is the 403/453 class. Log the details.
        try:
            code = getattr(e.response, "status_code", "unknown")
            msg = getattr(e, "api_codes", None) or str(e)
        except Exception:
            code, msg = "unknown", str(e)
        log.error(f"[X] post forbidden ({code}): {msg}")
        return False
    except Exception as e:
        log.error(f"[X] post error: {e}")
        return False
