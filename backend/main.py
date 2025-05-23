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
import time
import asyncio

DATABASE = "./app.db"
UPLOAD_DIR = "./uploads"
LOG_DIR = "./logs"
AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")

# Port range to allocate for running apps
PORT_START = int(os.environ.get("PORT_START", 9000))
PORT_END = int(os.environ.get("PORT_END", 9100))
AVAILABLE_PORTS = set(range(PORT_START, PORT_END))
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
            last_heartbeat REAL,
            url TEXT
        )
        """
    )
    # Add new columns if database existed before
    c.execute("PRAGMA table_info(apps)")
    cols = [row[1] for row in c.fetchall()]
    if "port" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN port INTEGER")
    if "last_heartbeat" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN last_heartbeat REAL")
    if "url" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN url TEXT")
    conn.commit()
    conn.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

init_db()

def release_app_port(app_id: str):
    """Return the port used by the app back to the pool."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT port FROM apps WHERE id=?", (app_id,))
    row = c.fetchone()
    if row and row[0] is not None:
        AVAILABLE_PORTS.add(row[0])
        c.execute("UPDATE apps SET port=NULL WHERE id=?", (app_id,))
        conn.commit()
    conn.close()

class StatusUpdate(BaseModel):
    app_id: str
    status: str

class Heartbeat(BaseModel):
    app_id: str

class StopRequest(BaseModel):
    app_id: str

def save_status(
    app_id: str,
    status: str = None,
    log_path: str = None,
    port: int = None,
    heartbeat: float = None,
    name: str = None,
    url: str = None,
):

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (app_id,))
    exists = c.fetchone()
    if exists:
        fields = []
        values = []
        if status is not None:
            fields.append("status=?")
            values.append(status)
        if log_path is not None:
            fields.append("log_path=?")
            values.append(log_path)
        if port is not None:
            fields.append("port=?")
            values.append(port)
        if heartbeat is not None:
            fields.append("last_heartbeat=?")
            values.append(heartbeat)
        if name is not None:
            fields.append("name=?")
            values.append(name)
        if url is not None:
            fields.append("url=?")
            values.append(url)
        if fields:
            values.append(app_id)
            c.execute(f"UPDATE apps SET {','.join(fields)} WHERE id=?", values)
    else:
        c.execute(
            "INSERT INTO apps(id, name, type, status, log_path, port, last_heartbeat, url) VALUES(?,?,?,?,?,?,?,?)",
            (app_id, name or app_id, '', status or '', log_path, port, heartbeat, url),

        )
    conn.commit()
    conn.close()

@app.post("/upload")
async def upload_app(
    name: str = Form(...),
    file: UploadFile = File(...),
    allow_ips: str = Form(None),
    auth_header: str = Form(None),
):

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

    # If zip file, extract safely
    if zipfile.is_zipfile(file_location):
        with zipfile.ZipFile(file_location, "r") as z:
            for member in z.namelist():
                # Reject absolute paths or traversals
                if os.path.isabs(member) or ".." in member.split("/"):
                    raise HTTPException(status_code=400, detail="invalid zip entry path")
                resolved = os.path.realpath(os.path.join(app_dir, member))
                if not resolved.startswith(os.path.realpath(app_dir) + os.sep):
                    raise HTTPException(status_code=400, detail="zip entry outside app directory")
            z.extractall(app_dir)

    # Detect app type
    app_type = "gradio"
    for root, _, files in os.walk(app_dir):
        for fname in files:
            if fname.lower() == "dockerfile":
                app_type = "docker"
                break
        if app_type == "docker":
            break

    log_path = os.path.join(LOG_DIR, f"{app_id}.log")
    # Allocate a port for the app
    if not AVAILABLE_PORTS:
        raise HTTPException(status_code=503, detail="no available ports")
    port = AVAILABLE_PORTS.pop()
    url = f"/apps/{app_id}/"
    save_status(app_id, "uploaded", log_path, port=port, name=name.strip(), url=url)


    # Request agent to run
    try:
        resp = requests.post(
            f"{AGENT_URL}/run",
            json={"app_id": app_id, "path": app_dir, "type": app_type, "log_path": log_path, "port": port},

            timeout=5
        )
        resp.raise_for_status()
        save_status(app_id, "running", log_path)
    except Exception as e:
        AVAILABLE_PORTS.add(port)
        save_status(app_id, "error", log_path)
        raise HTTPException(status_code=500, detail=str(e))

    return {"app_id": app_id, "status": "running", "url": url}

@app.post("/update_status")
async def update_status(update: StatusUpdate):
    save_status(update.app_id, update.status)
    if update.status in ("error", "finished"):
        release_app_port(update.app_id)
    return {"detail": "ok"}


@app.post("/heartbeat")
async def heartbeat(hb: Heartbeat):
    save_status(hb.app_id, heartbeat=time.time())
    return {"detail": "ok"}


@app.post("/stop")
async def stop_app(req: StopRequest):
    try:
        resp = requests.post(
            f"{AGENT_URL}/stop",
            json={"app_id": req.app_id},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    save_status(req.app_id, "finished")
    release_app_port(req.app_id)
    return {"detail": "stopped"}

@app.get("/status")
async def get_status():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, status, url FROM apps")
    rows = c.fetchall()
    conn.close()
    return [
        {"id": row[0], "status": row[1], "url": row[2] or f"/apps/{row[0]}/"}
        for row in rows
    ]

@app.get("/logs/{app_id}", response_class=PlainTextResponse)
async def get_logs(app_id: str):
    log_file = os.path.join(LOG_DIR, f"{app_id}.log")
    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail="log not found")
    with open(log_file) as f:
        return f.read()

async def cleanup_task():
    """Periodically check for apps without heartbeat and mark them as error."""
    while True:
        await asyncio.sleep(30)
        cutoff = time.time() - 60
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute(
            "SELECT id FROM apps WHERE status='running' AND (last_heartbeat IS NULL OR last_heartbeat<?)",
            (cutoff,),
        )
        stale = [row[0] for row in c.fetchall()]
        for app_id in stale:
            c.execute("UPDATE apps SET status='error' WHERE id=?", (app_id,))
            conn.commit()
            release_app_port(app_id)
        conn.close()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_task())


# Example: run with `uvicorn backend.main:app --reload`
