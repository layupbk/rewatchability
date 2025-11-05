# publisher_x.py
import os
import tweepy

_api = None

def _get_api() -> tweepy.API:
    global _api
    if _api:
        return _api

    key = os.getenv("X_API_KEY")
    secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("X_ACCESS_SECRET")

    missing = [n for n,v in {
        "X_API_KEY": key,
        "X_API_SECRET": secret,
        "X_ACCESS_TOKEN": access_token,
        "X_ACCESS_SECRET": access_secret
    }.items() if not v]
    if missing:
        raise RuntimeError(f"[X] Missing credentials: {', '.join(missing)}")

    auth = tweepy.OAuth1UserHandler(key, secret, access_token, access_secret)
    _api = tweepy.API(auth, wait_on_rate_limit=True)
    return _api

def post_to_x(text: str) -> bool:
    api = _get_api()
    try:
        # v1.1 text-only post (slice for safety)
        api.update_status(status=text[:280])
        print("[X] posted via v1.1", flush=True)
        return True
    except tweepy.TweepyException as e:
        print(f"[X] post error (v1.1): {e}", flush=True)
        return False

