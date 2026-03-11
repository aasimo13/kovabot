import os
import mimetypes
import logging

import db

logger = logging.getLogger(__name__)

FILES_DIR = os.environ.get("FILES_DIR", "/data/files")


def generate_file(filename: str, content: str, chat_id: int = 0) -> str:
    """Create a file and record it in the database. Returns a confirmation with the file ID."""
    os.makedirs(FILES_DIR, exist_ok=True)

    # Sanitize filename
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = "output.txt"

    path = os.path.join(FILES_DIR, f"{chat_id}_{safe_name}")

    # Avoid overwriting — append a counter if needed
    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(path):
        path = f"{base}_{counter}{ext}"
        counter += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    mime_type = mimetypes.guess_type(safe_name)[0] or "text/plain"
    file_id = db.save_file_upload(chat_id, safe_name, path, mime_type, "generated")

    logger.info(f"Generated file: {safe_name} (id={file_id}) for chat {chat_id}")
    return f"File created: {safe_name} (id={file_id}). The file will be sent to the user."
