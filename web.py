import os
import logging
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
from config import WEB_AUTH_TOKEN, WEB_CHAT_ID
from agent import run_agent
from tools import TOOL_SCHEMAS

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


def create_web_app() -> FastAPI:
    app = FastAPI(title="Kova Dashboard", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    def _check_auth(request: Request) -> bool:
        if not WEB_AUTH_TOKEN:
            return True  # No token configured = open access
        token = request.cookies.get("kova_token")
        return token == WEB_AUTH_TOKEN

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        # Handle token login via query param
        token = request.query_params.get("token")
        if token and token == WEB_AUTH_TOKEN:
            response = templates.TemplateResponse("index.html", {"request": request})
            response.set_cookie("kova_token", token, httponly=True, samesite="lax", secure=True, max_age=60 * 60 * 24 * 90)
            return response

        if not _check_auth(request):
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;'>"
                "<p>Access denied. Append <code>?token=YOUR_TOKEN</code> to the URL.</p>"
                "</body></html>",
                status_code=401,
            )

        return templates.TemplateResponse("index.html", {"request": request})

    @app.post("/api/chat")
    async def api_chat(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="Empty message")

        # Resolve custom commands: /name [input]
        if message.startswith("/"):
            parts = message[1:].split(None, 1)
            cmd_name = parts[0].lower() if parts else ""
            cmd_input = parts[1] if len(parts) > 1 else ""
            cmd = db.get_custom_command_by_name(cmd_name)
            if cmd:
                message = cmd["prompt_template"].replace("{input}", cmd_input).strip()

        chat_id = WEB_CHAT_ID
        if not chat_id:
            raise HTTPException(status_code=500, detail="WEB_CHAT_ID not configured")

        try:
            reply = await run_agent(chat_id, message)
            # Check for generated files
            import re
            file_ids = re.findall(r'\(id=(\d+)\)', reply)
            files = []
            for fid in file_ids:
                file_record = db.get_file_upload(int(fid))
                if file_record:
                    files.append({
                        "id": file_record["id"],
                        "filename": file_record["filename"],
                    })
            return JSONResponse({"reply": reply, "files": files})
        except Exception as e:
            logger.error(f"Web chat error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Agent error")

    @app.post("/api/upload")
    async def api_upload(request: Request, file: UploadFile = File(...), caption: str = Form("")):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        chat_id = WEB_CHAT_ID
        if not chat_id:
            raise HTTPException(status_code=500, detail="WEB_CHAT_ID not configured")

        file_bytes = await file.read()
        if len(file_bytes) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE // 1024 // 1024}MB)")
        filename = file.filename or "upload"
        mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Save upload to disk
        os.makedirs(FILES_DIR, exist_ok=True)
        safe_name = os.path.basename(filename)
        save_path = os.path.join(FILES_DIR, f"{chat_id}_upload_{safe_name}")
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        db.save_file_upload(chat_id, safe_name, save_path, mime, "web")

        # Process file based on type
        import io
        try:
            if mime.startswith("image/"):
                import base64
                b64 = base64.b64encode(file_bytes).decode("utf-8")
                content = [
                    {"type": "text", "text": caption or "What's in this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]
                reply = await run_agent(chat_id, content)
            elif mime == "application/pdf" or safe_name.lower().endswith(".pdf"):
                from handlers.messages import _extract_pdf_text
                text = _extract_pdf_text(file_bytes)
                if len(text) > 15000:
                    text = text[:15000] + "\n...(truncated)"
                user_message = f"[PDF: {safe_name}]\n{text}"
                if caption:
                    user_message = f"{caption}\n\n{user_message}"
                reply = await run_agent(chat_id, user_message)
            elif mime == "text/csv" or safe_name.lower().endswith(".csv"):
                from handlers.messages import _extract_csv_text
                text = _extract_csv_text(file_bytes)
                if len(text) > 15000:
                    text = text[:15000] + "\n...(truncated)"
                user_message = f"[CSV: {safe_name}]\n{text}"
                if caption:
                    user_message = f"{caption}\n\n{user_message}"
                reply = await run_agent(chat_id, user_message)
            elif safe_name.lower().endswith(".xlsx"):
                from handlers.messages import _extract_excel_text
                text = _extract_excel_text(file_bytes)
                if len(text) > 15000:
                    text = text[:15000] + "\n...(truncated)"
                user_message = f"[Excel: {safe_name}]\n{text}"
                if caption:
                    user_message = f"{caption}\n\n{user_message}"
                reply = await run_agent(chat_id, user_message)
            else:
                try:
                    text = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return JSONResponse({"reply": "This file type isn't supported yet. I can process text, PDF, CSV, Excel, and image files.", "files": []})

                if len(text) > 10000:
                    text = text[:10000] + "\n...(truncated)"
                user_message = f"[File: {safe_name}]\n{text}"
                if caption:
                    user_message = f"{caption}\n\n{user_message}"
                reply = await run_agent(chat_id, user_message)

            return JSONResponse({"reply": reply, "files": []})
        except Exception as e:
            logger.error(f"Web upload error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error processing file")

    @app.get("/api/history")
    async def api_history(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        chat_id = WEB_CHAT_ID
        if not chat_id:
            return JSONResponse({"messages": []})

        limit = int(request.query_params.get("limit", "50"))
        history = db.get_history(chat_id, limit=limit)
        return JSONResponse({"messages": history})

    @app.get("/api/memory")
    async def api_memory(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        chat_id = WEB_CHAT_ID
        if not chat_id:
            return JSONResponse({"facts": []})

        facts = db.get_facts(chat_id)
        return JSONResponse({"facts": facts})

    @app.get("/api/stats")
    async def api_stats(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        chat_id = WEB_CHAT_ID
        if not chat_id:
            return JSONResponse({})

        stats = db.get_stats(chat_id)
        return JSONResponse(stats)

    @app.get("/api/files")
    async def api_files(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        chat_id = WEB_CHAT_ID
        if not chat_id:
            return JSONResponse({"files": []})

        files = db.get_file_uploads(chat_id)
        return JSONResponse({"files": files})

    @app.get("/api/files/{file_id}")
    async def api_download_file(file_id: int, request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        file_record = db.get_file_upload(file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")

        if file_record["chat_id"] != WEB_CHAT_ID:
            raise HTTPException(status_code=403, detail="Forbidden")

        if not os.path.exists(file_record["path"]):
            raise HTTPException(status_code=404, detail="File not found on disk")

        return FileResponse(
            path=file_record["path"],
            filename=file_record["filename"],
            media_type=file_record["mime_type"] or "application/octet-stream",
        )

    # --- Tool management endpoints ---

    @app.get("/api/tools")
    async def api_tools(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        overrides = db.get_tool_overrides()
        tools = []
        for schema in TOOL_SCHEMAS:
            fn = schema["function"]
            name = fn["name"]
            override = overrides.get(name, {})
            params = list(fn.get("parameters", {}).get("properties", {}).keys())
            tools.append({
                "name": name,
                "description": fn["description"],
                "description_override": override.get("description_override"),
                "enabled": override.get("enabled", True),
                "parameters": params,
            })
        return JSONResponse({"tools": tools})

    @app.put("/api/tools/{name}")
    async def api_update_tool(name: str, request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        # Validate tool exists
        valid_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        if name not in valid_names:
            raise HTTPException(status_code=404, detail="Tool not found")

        body = await request.json()
        enabled = body.get("enabled")
        description_override = body.get("description_override")

        # Reset: delete override entirely
        if body.get("reset"):
            db.delete_tool_override(name)
            return JSONResponse({"ok": True})

        db.upsert_tool_override(name, enabled=enabled, description_override=description_override)
        return JSONResponse({"ok": True})

    # --- Custom command endpoints ---

    @app.get("/api/commands")
    async def api_commands(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        commands = db.get_custom_commands()
        return JSONResponse({"commands": commands})

    @app.post("/api/commands")
    async def api_create_command(request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        body = await request.json()
        name = body.get("name", "").strip().lower()
        description = body.get("description", "").strip()
        prompt_template = body.get("prompt_template", "").strip()

        if not name or not prompt_template:
            raise HTTPException(status_code=400, detail="Name and prompt_template are required")
        if not re.match(r'^[a-z0-9_]{1,32}$', name):
            raise HTTPException(status_code=400, detail="Name must be 1-32 chars: lowercase letters, numbers, underscores")
        if name in db.RESERVED_COMMANDS:
            raise HTTPException(status_code=400, detail=f"'{name}' is a reserved command name")
        if db.get_custom_command_by_name(name):
            raise HTTPException(status_code=400, detail=f"Command '{name}' already exists")

        cmd_id = db.create_custom_command(name, description, prompt_template)
        return JSONResponse({"id": cmd_id, "ok": True})

    @app.put("/api/commands/{command_id}")
    async def api_update_command(command_id: int, request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        cmd = db.get_custom_command(command_id)
        if not cmd:
            raise HTTPException(status_code=404, detail="Command not found")

        body = await request.json()
        name = body.get("name", "").strip().lower() if "name" in body else None
        description = body.get("description", "").strip() if "description" in body else None
        prompt_template = body.get("prompt_template", "").strip() if "prompt_template" in body else None

        if name and not re.match(r'^[a-z0-9_]{1,32}$', name):
            raise HTTPException(status_code=400, detail="Name must be 1-32 chars: lowercase letters, numbers, underscores")
        if name and name in db.RESERVED_COMMANDS:
            raise HTTPException(status_code=400, detail=f"'{name}' is a reserved command name")
        if name and name != cmd["name"]:
            existing = db.get_custom_command_by_name(name)
            if existing:
                raise HTTPException(status_code=400, detail=f"Command '{name}' already exists")

        db.update_custom_command(command_id, name=name, description=description, prompt_template=prompt_template)
        return JSONResponse({"ok": True})

    @app.delete("/api/commands/{command_id}")
    async def api_delete_command(command_id: int, request: Request):
        if not _check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")

        if not db.delete_custom_command(command_id):
            raise HTTPException(status_code=404, detail="Command not found")
        return JSONResponse({"ok": True})

    return app
