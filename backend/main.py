"""FastAPI backend for MLOps app deployment."""
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import shutil
import os
import uuid
import zipfile
import sqlite3
import requests
import re

DATABASE = "./app.db"
UPLOAD_DIR = "./uploads"
LOG_DIR = "./logs"
AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")
app = FastAPI()

# Serve the React frontend from the same origin
app.mount("/static", StaticFiles(directory="frontend"), name="frontend")

@app.get("/", include_in_schema=False)
async def frontend_index():
    """Return the frontend single-page app."""
    return FileResponse("frontend/index.html")

# Allowed pattern for uploaded filenames
ALLOWED_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            status TEXT,
            log_path TEXT,
            port INTEGER,
            url TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

init_db()

def get_free_port() -> int:
    """Return an available port between 9000 and 9999."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT port FROM apps WHERE port IS NOT NULL")
    used = {row[0] for row in c.fetchall()}
    conn.close()
    for port in range(9000, 10000):
        if port not in used:
            return port
    raise RuntimeError("no free ports available")

class StatusUpdate(BaseModel):
    app_id: str
    status: str



def save_status(app_id: str, status: str, log_path: str = None, name: str = None, app_type: str = None):

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (app_id,))
    exists = c.fetchone()
    if exists:
        c.execute(
            "UPDATE apps SET status=?, log_path=? WHERE id=?",
            (status, log_path, app_id),
        )
    else:
        c.execute(
            "INSERT INTO apps(id, name, type, status, log_path) VALUES(?,?,?,?,?)",
            (app_id, name or app_id, app_type or "", status, log_path),
        )
    conn.commit()
    conn.close()

@app.post("/upload")
async def upload_app(name: str = Form(...), file: UploadFile = File(...)):

    """Receive user uploaded app and trigger agent build/run."""
    # Reject duplicate app names
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE name=?", (name.strip(),))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="app name already exists")
    conn.close()
    app_id = str(uuid.uuid4())
    app_dir = os.path.join(UPLOAD_DIR, app_id)
    os.makedirs(app_dir, exist_ok=True)
    filename = os.path.basename(file.filename)
    if not ALLOWED_FILENAME.fullmatch(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    file_location = os.path.join(app_dir, filename)
    with open(file_location, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # If zip file, extract
    if zipfile.is_zipfile(file_location):
        with zipfile.ZipFile(file_location, 'r') as z:
            z.extractall(app_dir)

    # Detect app type
    app_type = "gradio"
    for root, _, files in os.walk(app_dir):
        for name in files:
            if name.lower() == "dockerfile":
                app_type = "docker"
                break
        if app_type == "docker":
            break

    log_path = os.path.join(LOG_DIR, f"{app_id}.log")
    save_status(app_id, "uploaded", log_path, name=name, app_type=app_type)

    # Request agent to run
    try:
        resp = requests.post(
            f"{AGENT_URL}/run",
            json={"app_id": app_id, "path": app_dir, "type": app_type, "log_path": log_path},
            timeout=5
        )
        resp.raise_for_status()
        save_status(app_id, "running", log_path)
    except Exception as e:
        save_status(app_id, "error", log_path)
        raise HTTPException(status_code=500, detail=str(e))

    return {"app_id": app_id, "status": "running", "url": url}

@app.post("/update_status")
async def update_status(update: StatusUpdate):
    save_status(update.app_id, update.status)
    return {"detail": "ok"}

@app.get("/status")
async def get_status():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, status, url FROM apps")
    rows = c.fetchall()
    conn.close()
    return [{"id": row[0], "status": row[1], "url": row[2]} for row in rows]

@app.get("/logs/{app_id}", response_class=PlainTextResponse)
async def get_logs(app_id: str):
    log_file = os.path.join(LOG_DIR, f"{app_id}.log")
    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail="log not found")
    with open(log_file) as f:
        return f.read()

@app.post("/stop/{app_id}")
async def stop_app(app_id: str):
    """Stop a running app via the agent and update status."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (app_id,))
    exists = c.fetchone()
    conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail="app not found")
    try:
        resp = requests.post(f"{AGENT_URL}/stop", json={"app_id": app_id}, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    save_status(app_id, "stopped")
    return {"detail": "stopped"}

@app.delete("/apps/{app_id}")
async def delete_app(app_id: str):
    """Remove uploaded files and logs after ensuring the app is stopped."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT status FROM apps WHERE id=?", (app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    status = row[0]
    if status != "stopped":
        conn.close()
        raise HTTPException(status_code=400, detail="app must be stopped first")
    app_dir = os.path.join(UPLOAD_DIR, app_id)
    shutil.rmtree(app_dir, ignore_errors=True)
    log_file = os.path.join(LOG_DIR, f"{app_id}.log")
    if os.path.exists(log_file):
        os.remove(log_file)
    c.execute("DELETE FROM apps WHERE id=?", (app_id,))
    conn.commit()
    conn.close()
    return {"detail": "deleted"}

# Example: run with `uvicorn backend.main:app --reload`
