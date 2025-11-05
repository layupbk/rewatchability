# publisher_x.py
import os
import tweepy

def _enabled() -> bool:
    return os.getenv("PUBLISH_X", "false").lower() == "true"

def _client():
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("X_ACCESS_TOKEN_SECRET")
    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("X creds missing. Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET")
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
    return tweepy.API(auth)

def post_to_x(text: str) -> bool:
    """Post a tweet. Returns True if posted; False if disabled."""
    if not _enabled():
        print("[X] disabled (set PUBLISH_X=true to enable)")
        return False
    tweet = text.strip()
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."
    try:
        api = _client()
        api.update_status(status=tweet)
        print("[X] posted ✅")
        return True
    except Exception as e:
        print(f"[X] post error: {e}")
        return False
