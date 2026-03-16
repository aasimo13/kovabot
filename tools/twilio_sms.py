import logging
from base64 import b64encode

import aiohttp

from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"


def _auth_header() -> dict:
    creds = b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


async def send_sms(to: str, body: str, chat_id: int = 0) -> str:
    """Send an SMS message via Twilio."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{BASE_URL}/Messages.json"
            data = {"To": to, "From": TWILIO_PHONE_NUMBER, "Body": body}
            async with session.post(
                url,
                headers=_auth_header(),
                data=data,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                if resp.status not in (200, 201):
                    error_msg = result.get("message", resp.status)
                    return f"Twilio API error: {error_msg}"

        sid = result.get("sid", "unknown")
        status = result.get("status", "unknown")
        return f"SMS sent to {to} — SID: {sid}, status: {status}"
    except Exception as e:
        logger.error(f"send_sms error: {e}")
        return f"Error sending SMS: {e}"


async def get_sms_history(phone_number: str, limit: int = 10, chat_id: int = 0) -> str:
    """Fetch recent SMS messages exchanged with a phone number."""
    try:
        messages = []
        async with aiohttp.ClientSession() as session:
            # Messages sent TO the number
            url = f"{BASE_URL}/Messages.json"
            params_to = {"To": phone_number, "From": TWILIO_PHONE_NUMBER, "PageSize": limit}
            async with session.get(
                url,
                headers=_auth_header(),
                params=params_to,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    messages.extend(data.get("messages", []))

            # Messages received FROM the number
            params_from = {"From": phone_number, "To": TWILIO_PHONE_NUMBER, "PageSize": limit}
            async with session.get(
                url,
                headers=_auth_header(),
                params=params_from,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    messages.extend(data.get("messages", []))

        if not messages:
            return f"No SMS history found with {phone_number}."

        # Sort by date, newest first
        messages.sort(key=lambda m: m.get("date_sent", ""), reverse=True)
        messages = messages[:limit]

        lines = [f"SMS history with {phone_number}:"]
        for msg in messages:
            direction = "Sent" if msg.get("from") == TWILIO_PHONE_NUMBER else "Received"
            date = msg.get("date_sent", "unknown")[:19]
            body = msg.get("body", "")[:100]
            lines.append(f"- [{direction}] {date}: {body}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_sms_history error: {e}")
        return f"Error fetching SMS history: {e}"
