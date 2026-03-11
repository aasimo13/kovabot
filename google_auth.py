import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import aiohttp

import db
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def get_auth_url(state: str = "") -> str:
    """Generate Google OAuth2 authorization URL."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, chat_id: int) -> bool:
    """Exchange authorization code for tokens and save them."""
    try:
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error(f"OAuth token exchange failed: {err}")
                    return False
                tokens = await resp.json()

        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat()
        db.save_oauth_token(
            chat_id=chat_id,
            provider="google",
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            expires_at=expires_at,
            scope=" ".join(SCOPES),
        )
        return True
    except Exception as e:
        logger.error(f"OAuth exchange error: {e}")
        return False


async def refresh_access_token(chat_id: int) -> str | None:
    """Refresh an expired access token. Returns new access token or None."""
    token_data = db.get_oauth_token(chat_id, "google")
    if not token_data or not token_data["refresh_token"]:
        return None

    try:
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error(f"Token refresh failed: {await resp.text()}")
                    return None
                tokens = await resp.json()

        new_access = tokens["access_token"]
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat()
        db.save_oauth_token(
            chat_id=chat_id,
            provider="google",
            access_token=new_access,
            refresh_token=token_data["refresh_token"],
            expires_at=expires_at,
            scope=token_data.get("scope", " ".join(SCOPES)),
        )
        return new_access
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None


async def get_valid_token(chat_id: int) -> str | None:
    """Get a valid access token, refreshing if needed."""
    token_data = db.get_oauth_token(chat_id, "google")
    if not token_data:
        return None

    # Check if expired
    try:
        expires = datetime.fromisoformat(token_data["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expires - timedelta(minutes=5):
            return token_data["access_token"]
    except (ValueError, KeyError):
        pass

    # Refresh
    return await refresh_access_token(chat_id)
