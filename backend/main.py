"""FastAPI backend for MLOps app deployment."""
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import shutil
import os
import uuid
import zipfile
import sqlite3
import httpx
import re
import time
import asyncio
import socket

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

def is_port_free(port: int) -> bool:
    """Check if a TCP port is available."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()

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
    app_type: str = None,
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
        if app_type is not None:
            fields.append("type=?")
            values.append(app_type)
        if fields:
            values.append(app_id)
            c.execute(f"UPDATE apps SET {','.join(fields)} WHERE id=?", values)
    else:
        c.execute(
            "INSERT INTO apps(id, name, type, status, log_path, port, last_heartbeat, url) VALUES(?,?,?,?,?,?,?,?)",
            (
                app_id,
                name or app_id,
                app_type or "",
                status or "",
                log_path,
                port,
                heartbeat,
                url,
            ),

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
    allowed = [ip.strip() for ip in allow_ips.split(',')] if allow_ips else None
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
    if filename.lower().endswith(".tar"):
        app_type = "docker_tar"
    else:
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
    port = None
    while AVAILABLE_PORTS:
        candidate = AVAILABLE_PORTS.pop()
        if is_port_free(candidate):
            port = candidate
            break
        # port was busy, keep looking
    if port is None:
        raise HTTPException(status_code=503, detail="no available ports")
    url = f"/apps/{app_id}/"
    save_status(
        app_id,
        "uploaded",
        log_path,
        port=port,
        name=name.strip(),
        url=url,
        app_type=app_type,
    )


    # Path sent to the agent depends on app type
    run_path = file_location if app_type == "docker_tar" else app_dir

    # Request agent to run
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AGENT_URL}/run",
                json={
                    "app_id": app_id,
                    "path": run_path,
                    "type": app_type,
                    "log_path": log_path,
                    "port": port,
                    "allow_ips": allowed,
                    "auth_header": auth_header,
                },
                timeout=5,
            )
            resp.raise_for_status()
        save_status(app_id, "running", log_path, app_type=app_type)
    except httpx.ConnectError:
        AVAILABLE_PORTS.add(port)
        save_status(app_id, "error", log_path, app_type=app_type)
        raise HTTPException(
            status_code=502,
            detail="Unable to reach agent. Please ensure the agent is running and reachable.",
        )
    except httpx.TimeoutException:
        AVAILABLE_PORTS.add(port)
        save_status(app_id, "error", log_path, app_type=app_type)
        raise HTTPException(
            status_code=504,
            detail="Agent request timed out. Please make sure the agent is running.",
        )
    except Exception as e:
        AVAILABLE_PORTS.add(port)
        save_status(app_id, "error", log_path, app_type=app_type)
        raise HTTPException(status_code=500, detail=str(e))

    return {"app_id": app_id, "status": "running", "url": url}

@app.post("/update_status")
async def update_status(update: StatusUpdate):
    save_status(update.app_id, update.status)
    if update.status in ("error", "finished", "stopped"):
        release_app_port(update.app_id)
    return {"detail": "ok"}


@app.post("/heartbeat")
async def heartbeat(hb: Heartbeat):
    save_status(hb.app_id, heartbeat=time.time())
    return {"detail": "ok"}


@app.post("/stop")
async def stop_app(req: StopRequest, background_tasks: BackgroundTasks):
    # It might be good to add a check here if app_id from req.app_id exists, similar to stop_app_by_id.
    # For now, proceeding as per the direct conversion of existing logic.
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (req.app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    conn.close()

    save_status(req.app_id, "stopping")
    background_tasks.add_task(_stop_agent_and_update_status, req.app_id)
    return {"detail": "stopping process initiated"}


async def _stop_agent_and_update_status(app_id: str):
    """Helper function to stop agent and update status in the background."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{AGENT_URL}/stop",
                json={"app_id": app_id},
                timeout=5,
            )
    except Exception as e:
        # Log this error or handle it more gracefully
        # For now, we'll proceed to update status to avoid app being stuck in "stopping"
        print(f"Error stopping agent for {app_id}: {e}")
        save_status(app_id, "error") # Or a more specific error status
        release_app_port(app_id)
        return

    save_status(app_id, "stopped")
    release_app_port(app_id)

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


@app.post("/stop/{app_id}")
async def stop_app_by_id(app_id: str, background_tasks: BackgroundTasks):
    """Stop a running app via the agent and mark it stopped."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    conn.close()

    save_status(app_id, "stopping")
    background_tasks.add_task(_stop_agent_and_update_status, app_id)
    return {"detail": "stopping process initiated"}


@app.delete("/apps/{app_id}")
async def delete_app(app_id: str):
    """Delete an app and all its data."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT status FROM apps WHERE id=?", (app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    status = row[0]
    conn.close()

    if status == "running":
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{AGENT_URL}/stop",
                    json={"app_id": app_id},
                    timeout=5,
                )
        except Exception:
            pass
    else:
        # Ensure the proxy route is removed for non-running apps
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{AGENT_URL}/remove_route",
                    json={"app_id": app_id},
                    timeout=5,
                )
        except Exception:
            pass

    release_app_port(app_id)

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM apps WHERE id=?", (app_id,))
    conn.commit()
    conn.close()

    shutil.rmtree(os.path.join(UPLOAD_DIR, app_id), ignore_errors=True)
    log_file = os.path.join(LOG_DIR, f"{app_id}.log")
    if os.path.exists(log_file):
        os.remove(log_file)

    return {"detail": "deleted"}

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
            # Attempt to stop the app on the agent so lingering processes and
            # proxy routes are cleaned up. If stopping fails (e.g. the agent no
            # longer has a record of the app), fall back to removing the proxy
            # route directly.
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{AGENT_URL}/stop",
                        json={"app_id": app_id},
                        timeout=5,
                    )
                    resp.raise_for_status()
            except Exception:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{AGENT_URL}/remove_route",
                            json={"app_id": app_id},
                            timeout=5,
                        )
                except Exception:
                    pass
        conn.close()


@app.on_event("startup")
async def startup_event():
    # Remove ports for any apps that are already running
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "SELECT port FROM apps WHERE status='running' AND port IS NOT NULL"
    )
    rows = c.fetchall()
    conn.close()
    for row in rows:
        port = row[0]
        if port in AVAILABLE_PORTS:
            AVAILABLE_PORTS.remove(port)

    asyncio.create_task(cleanup_task())


# Example: run with `uvicorn backend.main:app --reload`
