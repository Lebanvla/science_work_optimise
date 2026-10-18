from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from cleaner import cleaner_loop
from config import (
    ALLOWED_EXTENSIONS,
    INPUT_DIR,
    MAX_UPLOAD_SIZE_BYTES,
    OUTPUT_DIR,
    TEMPLATES_DIR,
    WORKER_TOKEN,
    ensure_directories,
)
from database import get_conn, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

ensure_directories()
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleaner_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Road Segmentation Server", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")


def require_worker_token(authorization: str | None = Header(default=None)) -> None:
    if not WORKER_TOKEN:
        raise HTTPException(status_code=500, detail="WORKER_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, WORKER_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid token")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


def _validate_extension(filename: str | None) -> str:
    if not filename:
        raise HTTPException(400, "File name is required")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type. Allowed: {sorted(ALLOWED_EXTENSIONS)}")
    return ext


def _validate_image_bytes(content: bytes) -> None:
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(413, "Uploaded file is too large")
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "Uploaded file is not a valid image") from exc


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    ext = _validate_extension(file.filename)
    content = await file.read()
    _validate_image_bytes(content)

    picture_hash = hashlib.sha256(content).hexdigest()
    input_path = INPUT_DIR / f"{picture_hash}{ext}"
    input_path.write_bytes(content)

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(picture_hash, status, input_path) VALUES (?, 'pending', ?)",
            (picture_hash, str(input_path)),
        )
        task_id = cur.lastrowid

    logger.info("Enqueued task id=%s hash=%s", task_id, picture_hash)
    return {"status": "queued", "task_id": task_id, "picture_hash": picture_hash}


@app.get("/get/{picture_hash}")
def get_result(picture_hash: str):
    if not _HEX_64_RE.match(picture_hash):
        raise HTTPException(400, "Invalid picture_hash format")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, status, result_path, error_message
              FROM tasks
             WHERE picture_hash = ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (picture_hash,),
        ).fetchone()

    if row is None or row["status"] in ("pending", "processing"):
        return {"status": "processing"}
    if row["status"] == "failed":
        return {"status": "error", "message": row["error_message"] or "Unknown error"}
    if row["status"] == "done":
        if not row["result_path"]:
            return {"status": "error", "message": "Result file was already cleaned up. Please upload again."}
        filename = Path(row["result_path"]).name
        return {"status": "ready", "url": f"/static/output/{filename}"}

    return {"status": "processing"}


@app.get("/worker/tasks/pending", dependencies=[Depends(require_worker_token)])
def worker_get_pending():
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT id, picture_hash, input_path
              FROM tasks
             WHERE status = 'pending'
             ORDER BY id
             LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return {"task": None}

        conn.execute(
            "UPDATE tasks SET status='processing', started_at=datetime('now') WHERE id = ?",
            (row["id"],),
        )
        conn.execute("COMMIT")

    return {
        "task": {
            "id": row["id"],
            "picture_hash": row["picture_hash"],
            "input_path": row["input_path"],
        }
    }


@app.get("/worker/tasks/{task_id}/image", dependencies=[Depends(require_worker_token)])
def worker_get_image(task_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT input_path, status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(404, "Task not found")
    if not row["input_path"] or not Path(row["input_path"]).exists():
        raise HTTPException(410, "Input file is no longer available")
    return FileResponse(row["input_path"])


@app.post("/worker/tasks/{task_id}/result", dependencies=[Depends(require_worker_token)])
async def worker_submit_result(task_id: int, file: UploadFile = File(...)):
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    if row["status"] not in ("processing", "pending"):
        raise HTTPException(409, f"Task is in status '{row['status']}', cannot accept result")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty result file")

    output_hash = hashlib.sha256(content + str(task_id).encode()).hexdigest()
    output_path = OUTPUT_DIR / f"{output_hash}.png"
    output_path.write_bytes(content)

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
               SET status='done',
                   result_path=?,
                   completed_at=datetime('now'),
                   error_message=NULL
             WHERE id = ?
            """,
            (str(output_path), task_id),
        )

    logger.info("Task %s completed -> %s", task_id, output_path)
    return {"status": "ok"}


@app.post("/worker/tasks/{task_id}/fail", dependencies=[Depends(require_worker_token)])
def worker_submit_failure(task_id: int, payload: dict):
    message = str(payload.get("message", "Unknown error"))[:500]
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tasks
               SET status='failed',
                   error_message=?,
                   completed_at=datetime('now')
             WHERE id = ? AND status IN ('pending', 'processing')
            """,
            (message, task_id),
        )
    logger.warning("Task %s failed: %s", task_id, message)
    return {"status": "ok"}