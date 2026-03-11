import os
import logging
import tempfile

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, TTS_MODEL, TTS_VOICE

logger = logging.getLogger(__name__)

FILES_DIR = os.environ.get("FILES_DIR", "/data/files")


async def text_to_speech(text: str, chat_id: int = 0) -> str:
    """Convert text to a voice audio message using OpenAI TTS API."""
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        os.makedirs(FILES_DIR, exist_ok=True)

        # Generate speech
        response = await client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text[:4096],  # TTS API limit
            response_format="opus",
        )

        # Save to file
        suffix = f"_{chat_id}_{os.urandom(4).hex()}.opus"
        filepath = os.path.join(FILES_DIR, f"tts{suffix}")
        response.stream_to_file(filepath)

        # Save to DB
        import db
        file_id = db.save_file_upload(chat_id, f"tts{suffix}", filepath, "audio/opus", "tts")

        return f"TTS_AUDIO_FILE:{filepath}:{file_id}"
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return f"Error generating speech: {e}"
