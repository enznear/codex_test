"""FastAPI backend for MLOps app deployment."""

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Form,
    BackgroundTasks,
    Depends,
    status,
)
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import shutil
import os
import subprocess
import stat
import uuid
import zipfile
import sqlite3
import httpx
import re
import time
import asyncio
import socket
from typing import List
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

DATABASE = "./app.db"
UPLOAD_DIR = "./uploads"
LOG_DIR = "./logs"
TEMPLATE_DIR = "./templates"
AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8001")

# Port range to allocate for running apps
PORT_START = int(os.environ.get("PORT_START", 9000))
PORT_END = int(os.environ.get("PORT_END", 9100))
AVAILABLE_PORTS = set(range(PORT_START, PORT_END))
app = FastAPI()


def force_rmtree(path: str):
    """Remove a directory tree, adjusting permissions if needed."""
    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, ignore_errors=True, onerror=_onerror)
    if os.path.exists(path) and os.name != "nt":
        subprocess.run(["rm", "-rf", path], check=False)

# Authentication setup
SECRET_KEY = os.environ.get("SECRET_KEY", "change_me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


# Serve the React frontend from the same origin
app.mount("/static", StaticFiles(directory="frontend"), name="frontend")


@app.get("/", include_in_schema=False)
async def frontend_index():
    """Return the frontend single-page app."""
    return FileResponse("frontend/index.html")


# Allowed pattern for uploaded filenames
ALLOWED_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user(username: str):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username=?",
        (username,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "is_admin": bool(row[3]),
        }
    return None


def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user


def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            type TEXT,
            status TEXT,
            log_path TEXT,
            port INTEGER,
            last_heartbeat REAL,
            url TEXT,
            allow_ips TEXT,
            auth_header TEXT,
            gpus TEXT,
            vram_required INTEGER
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            path TEXT,
            description TEXT,
            vram_required INTEGER
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            is_admin INTEGER DEFAULT 0
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
    if "allow_ips" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN allow_ips TEXT")
    if "auth_header" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN auth_header TEXT")
    if "gpus" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN gpus TEXT")
    if "vram_required" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN vram_required INTEGER")
    if "description" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN description TEXT")
    # Add new columns to users table if needed
    c.execute("PRAGMA table_info(users)")
    u_cols = [row[1] for row in c.fetchall()]
    if "is_admin" not in u_cols:
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

    # Add new columns to templates table if needed
    c.execute("PRAGMA table_info(templates)")
    t_cols = [row[1] for row in c.fetchall()]
    if "vram_required" not in t_cols:
        c.execute("ALTER TABLE templates ADD COLUMN vram_required INTEGER")
    conn.commit()
    conn.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # Ensure admin user exists
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute(
            "INSERT INTO users(username, password_hash, is_admin) VALUES(?, ?, 1)",
            ("admin", get_password_hash(ADMIN_PASSWORD)),
        )
        conn.commit()
    conn.close()


init_db()


def ensure_templates():
    """Scan TEMPLATE_DIR for folders and register them as templates."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM templates")
    known = {row[0] for row in c.fetchall()}
    for entry in os.listdir(TEMPLATE_DIR):
        full = os.path.join(TEMPLATE_DIR, entry)
        if not os.path.isdir(full) or entry in known:
            continue
        app_type = "gradio"
        stored_path = "."
        for root, _, files in os.walk(full):
            for fname in files:
                lower = fname.lower()
                if lower.endswith(".tar"):
                    app_type = "docker_tar"
                    stored_path = fname
                    break
                if lower in ("docker-compose.yml", "docker-compose.yaml"):
                    app_type = "docker_compose"
                    stored_path = os.path.relpath(os.path.join(root, fname), full)
                    break
                if lower == "dockerfile":
                    app_type = "docker"
                    break
            if app_type != "gradio":
                break
        c.execute(
            "INSERT INTO templates(id, name, type, path, description, vram_required) VALUES(?,?,?,?,?,?)",
            (entry, entry, app_type, stored_path, "", 0),
        )
    conn.commit()
    conn.close()


ensure_templates()


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


@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="username already exists")
    c.execute(
        "INSERT INTO users(username, password_hash) VALUES(?, ?)",
        (username, get_password_hash(password)),
    )
    conn.commit()
    conn.close()
    return {"detail": "user created"}


@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    access_token = create_access_token({"sub": user["username"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_admin": bool(user.get("is_admin", False)),
        "username": user["username"],
    }


@app.get("/users/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "is_admin": current_user.get("is_admin", False),
    }


@app.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, username, is_admin FROM users")
    users = [
        {"id": row[0], "username": row[1], "is_admin": bool(row[2])}
        for row in c.fetchall()
    ]
    conn.close()
    return users


@app.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="user not found")
    if row[0] == "admin":
        conn.close()
        raise HTTPException(status_code=400, detail="cannot delete admin user")
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"detail": "deleted"}


@app.post("/users/{user_id}/reset_password")
async def reset_password(
    user_id: int,
    new_password: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="user not found")
    c.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (get_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()
    return {"detail": "password reset"}


class StatusUpdate(BaseModel):
    app_id: str
    status: str
    gpus: List[int] | None = None


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
    description: str = None,
    url: str = None,
    app_type: str = None,
    allow_ips: str = None,
    auth_header: str = None,
    gpus: List[int] | None = None,
    vram_required: int = None,
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
        if description is not None:
            fields.append("description=?")
            values.append(description)
        if url is not None:
            fields.append("url=?")
            values.append(url)
        if app_type is not None:
            fields.append("type=?")
            values.append(app_type)
        if allow_ips is not None:
            fields.append("allow_ips=?")
            values.append(allow_ips)
        if auth_header is not None:
            fields.append("auth_header=?")
            values.append(auth_header)
        if gpus is not None:
            fields.append("gpus=?")
            values.append(",".join(map(str, gpus)))
        if vram_required is not None:
            fields.append("vram_required=?")
            values.append(vram_required)
        if fields:
            values.append(app_id)
            c.execute(f"UPDATE apps SET {','.join(fields)} WHERE id=?", values)
    else:
        c.execute(
            "INSERT INTO apps(id, name, description, type, status, log_path, port, last_heartbeat, url, allow_ips, auth_header, gpus, vram_required) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                app_id,
                name or app_id,
                description,
                app_type or "",
                status or "",
                log_path,
                port,
                heartbeat,
                url,
                allow_ips,
                auth_header,
                ",".join(map(str, gpus)) if gpus is not None else None,
                vram_required,
            ),
        )
    conn.commit()
    conn.close()


@app.post("/upload")
async def upload_app(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: str = Form(""),
    allow_ips: str = Form(None),
    auth_header: str = Form(None),
    vram_required: int = Form(0),
    current_user: dict = Depends(get_current_user),
):
    """Receive user uploaded app and trigger agent build/run."""
    allowed = [ip.strip() for ip in allow_ips.split(",")] if allow_ips else None
    allowed_str = ",".join(allowed) if allowed else None
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
                    raise HTTPException(
                        status_code=400, detail="invalid zip entry path"
                    )
                resolved = os.path.realpath(os.path.join(app_dir, member))
                if not resolved.startswith(os.path.realpath(app_dir) + os.sep):
                    raise HTTPException(
                        status_code=400, detail="zip entry outside app directory"
                    )
            z.extractall(app_dir)

    # Detect app type
    compose_file = None
    if filename.lower().endswith(".tar"):
        app_type = "docker_tar"
    else:
        app_type = "gradio"
        for root, _, files in os.walk(app_dir):
            for fname in files:
                lower = fname.lower()
                if lower in ("docker-compose.yml", "docker-compose.yaml"):
                    app_type = "docker_compose"
                    compose_file = os.path.join(root, fname)
                    break
                if lower == "dockerfile":
                    app_type = "docker"
                    break
            if app_type in ("docker", "docker_compose"):
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
        description=description.strip() if description else None,
        url=url,
        app_type=app_type,
        allow_ips=allowed_str,
        auth_header=auth_header,
        vram_required=vram_required,
    )

    # Path sent to the agent depends on app type
    if app_type == "docker_tar":
        run_path = file_location
    elif app_type == "docker_compose":
        run_path = os.path.dirname(compose_file) if compose_file else app_dir
    else:
        run_path = app_dir

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
                    "vram_required": vram_required,
                },
                timeout=5,
            )
            resp.raise_for_status()
        save_status(
            app_id,
            "building",
            log_path,
            description=description.strip() if description else None,
            app_type=app_type,
            allow_ips=allowed_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
    except httpx.ConnectError:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            allow_ips=allowed_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to reach agent. Please ensure the agent is running and reachable.",
        )
    except httpx.TimeoutException:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            allow_ips=allowed_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
        raise HTTPException(
            status_code=504,
            detail="Agent request timed out. Please make sure the agent is running.",
        )
    except Exception as e:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            allow_ips=allowed_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
        raise HTTPException(status_code=500, detail=str(e))

    return {"app_id": app_id, "status": "building", "url": url}


@app.post("/templates")
async def upload_template(
    name: str = Form(...),
    file: UploadFile = File(...),
    description: str = Form(""),
    vram_required: int = Form(0),
    current_user: dict = Depends(get_current_user),
):
    """Upload a template archive or file."""
    template_id = str(uuid.uuid4())
    t_dir = os.path.join(TEMPLATE_DIR, template_id)
    os.makedirs(t_dir, exist_ok=True)
    filename = os.path.basename(file.filename)
    if not ALLOWED_FILENAME.fullmatch(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    file_location = os.path.join(t_dir, filename)
    with open(file_location, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if zipfile.is_zipfile(file_location):
        with zipfile.ZipFile(file_location, "r") as z:
            for member in z.namelist():
                if os.path.isabs(member) or ".." in member.split("/"):
                    raise HTTPException(
                        status_code=400, detail="invalid zip entry path"
                    )
                resolved = os.path.realpath(os.path.join(t_dir, member))
                if not resolved.startswith(os.path.realpath(t_dir) + os.sep):
                    raise HTTPException(
                        status_code=400, detail="zip entry outside template directory"
                    )
            z.extractall(t_dir)

    if filename.lower().endswith(".tar"):
        app_type = "docker_tar"
        stored_path = filename
    else:
        app_type = "gradio"
        stored_path = "."
        for root, _, files in os.walk(t_dir):
            for fname in files:
                lower = fname.lower()
                if lower in ("docker-compose.yml", "docker-compose.yaml"):
                    app_type = "docker_compose"
                    stored_path = os.path.relpath(os.path.join(root, fname), t_dir)
                    break
                if lower == "dockerfile":
                    app_type = "docker"
                    break
            if app_type != "gradio":
                break

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO templates(id, name, type, path, description, vram_required) VALUES(?,?,?,?,?,?)",
        (
            template_id,
            name.strip(),
            app_type,
            stored_path,
            description.strip(),
            vram_required,
        ),
    )
    conn.commit()
    conn.close()

    return {"template_id": template_id}


@app.delete("/templates/{template_id}")
async def delete_template(template_id: str):
    """Remove a saved template and its files."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM templates WHERE id=?", (template_id,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="template not found")
    c.execute("DELETE FROM templates WHERE id=?", (template_id,))
    conn.commit()
    conn.close()

    force_rmtree(os.path.join(TEMPLATE_DIR, template_id))

    return {"detail": "deleted"}


@app.get("/templates")
async def list_templates():
    ensure_templates()

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, name, description, type, vram_required FROM templates")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "type": row[3],
            "vram_required": row[4] or 0,
        }
        for row in rows
    ]


@app.post("/deploy_template/{template_id}")
async def deploy_template(template_id: str, vram_required: int | None = Form(None)):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "SELECT name, type, path, description, vram_required FROM templates WHERE id=?",
        (template_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="template not found")
    name, app_type, stored_path, description, template_vram = row

    app_id = str(uuid.uuid4())
    app_dir = os.path.join(UPLOAD_DIR, app_id)
    shutil.copytree(os.path.join(TEMPLATE_DIR, template_id), app_dir)

    log_path = os.path.join(LOG_DIR, f"{app_id}.log")
    if not AVAILABLE_PORTS:
        raise HTTPException(status_code=503, detail="no available ports")
    port = None
    while AVAILABLE_PORTS:
        candidate = AVAILABLE_PORTS.pop()
        if is_port_free(candidate):
            port = candidate
            break
    if port is None:
        raise HTTPException(status_code=503, detail="no available ports")

    if vram_required is None:
        vram_required = template_vram

    url = f"/apps/{app_id}/"
    save_status(
        app_id,
        "uploaded",
        log_path,
        port=port,
        name=name,
        url=url,
        app_type=app_type,
        vram_required=vram_required,
        description=description.strip() if description else None,
    )

    if app_type == "docker_compose" and stored_path and stored_path != ".":
        run_path = os.path.join(app_dir, os.path.dirname(stored_path))
    else:
        run_path = os.path.join(app_dir, stored_path) if stored_path and stored_path != "." else app_dir

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
                    "allow_ips": None,
                    "auth_header": None,
                    "vram_required": vram_required,
                },
                timeout=5,
            )
            resp.raise_for_status()
        save_status(
            app_id,
            "building",
            log_path,
            app_type=app_type,
            vram_required=vram_required,
            description=description.strip() if description else None,
        )
    except httpx.ConnectError:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            vram_required=vram_required,
            description=description.strip() if description else None,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to reach agent. Please ensure the agent is running and reachable.",
        )
    except httpx.TimeoutException:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            vram_required=vram_required,
            description=description.strip() if description else None,
        )
        raise HTTPException(
            status_code=504,
            detail="Agent request timed out. Please make sure the agent is running.",
        )
    except Exception as e:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            vram_required=vram_required,
            description=description.strip() if description else None,
        )
        raise HTTPException(status_code=500, detail=str(e))

    return {"app_id": app_id, "url": url}


@app.post("/update_status")
async def update_status(update: StatusUpdate):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (update.app_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="app not found")

    heartbeat_time = time.time() if update.status == "running" else None
    save_status(update.app_id, update.status, heartbeat=heartbeat_time, gpus=update.gpus)
    if update.status in ("error", "finished", "stopped"):
        release_app_port(update.app_id)
    return {"detail": "ok"}


@app.post("/heartbeat")
async def heartbeat(hb: Heartbeat):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (hb.app_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="app not found")

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
                timeout=30,
            )
    except Exception as e:
        # Log this error or handle it more gracefully
        # For now, we'll proceed to update status to avoid app being stuck in "stopping"
        print(f"Error stopping agent for {app_id}: {e}")
        save_status(app_id, "error", gpus=None)  # Or a more specific error status
        release_app_port(app_id)
        return

    save_status(app_id, "stopped", gpus=None)
    release_app_port(app_id)


@app.get("/status")
async def get_status():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, name, description, status, url, gpus FROM apps")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "name": row[1],
            "status": row[3],
            "url": row[4] or f"/apps/{row[0]}/",
            "gpus": [int(x) for x in row[5].split(',')] if row[5] else [],
            "description": row[2] or "",
        }
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


@app.post("/restart/{app_id}")
async def restart_app(app_id: str):
    """Restart a previously uploaded app using its existing image."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "SELECT type, log_path, port, allow_ips, auth_header, vram_required FROM apps WHERE id=?",
        (app_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    app_type, log_path, stored_port, allow_ips_str, auth_header, vram_required = row
    conn.close()

    allowed = [ip.strip() for ip in allow_ips_str.split(",")] if allow_ips_str else None

    app_dir = os.path.join(UPLOAD_DIR, app_id)
    if app_type == "docker_tar":
        files = [f for f in os.listdir(app_dir) if f.endswith(".tar")]
        if not files:
            raise HTTPException(status_code=500, detail="tar file missing")
        run_path = os.path.join(app_dir, files[0])
    elif app_type == "docker_compose":
        compose = None
        for root, _, files in os.walk(app_dir):
            for fname in files:
                if fname.lower() in ("docker-compose.yml", "docker-compose.yaml"):
                    compose = os.path.join(root, fname)
                    break
            if compose:
                break
        if not compose:
            raise HTTPException(status_code=500, detail="compose file missing")
        run_path = os.path.dirname(compose)
    else:
        run_path = app_dir

    port = stored_port if stored_port and is_port_free(stored_port) else None
    if port is not None and port in AVAILABLE_PORTS:
        AVAILABLE_PORTS.remove(port)
    if port is None:
        if not AVAILABLE_PORTS:
            raise HTTPException(status_code=503, detail="no available ports")
        while AVAILABLE_PORTS:
            candidate = AVAILABLE_PORTS.pop()
            if is_port_free(candidate):
                port = candidate
                break
        if port is None:
            raise HTTPException(status_code=503, detail="no available ports")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AGENT_URL}/restart",
                json={
                    "app_id": app_id,
                    "path": run_path,
                    "type": app_type,
                    "log_path": log_path,
                    "port": port,
                    "allow_ips": allowed,
                    "auth_header": auth_header,
                    "vram_required": vram_required,
                },
                timeout=5,
            )
            resp.raise_for_status()
        save_status(
            app_id,
            "building",
            log_path,
            port=port,
            app_type=app_type,
            allow_ips=allow_ips_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
    except Exception as e:
        AVAILABLE_PORTS.add(port)
        save_status(
            app_id,
            "error",
            log_path,
            app_type=app_type,
            allow_ips=allow_ips_str,
            auth_header=auth_header,
            vram_required=vram_required,
        )
        raise HTTPException(status_code=500, detail=str(e))

    return {"detail": "restarting", "url": f"/apps/{app_id}/"}


@app.post("/save_template/{app_id}")
async def save_template_from_app(app_id: str):
    """Save an uploaded app as a reusable template."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "SELECT name, description, type, vram_required FROM apps WHERE id=?",
        (app_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="app not found")
    name, description, app_type, vram_required = row

    template_id = str(uuid.uuid4())
    src_dir = os.path.join(UPLOAD_DIR, app_id)
    dst_dir = os.path.join(TEMPLATE_DIR, template_id)
    shutil.copytree(src_dir, dst_dir)

    if app_type == "docker_tar":
        files = [f for f in os.listdir(dst_dir) if f.endswith(".tar")]
        if not files:
            force_rmtree(dst_dir)
            raise HTTPException(status_code=500, detail="tar file missing")
        stored_path = files[0]
    else:
        stored_path = "."
        for root, _, files in os.walk(dst_dir):
            for fname in files:
                lower = fname.lower()
                if lower in ("docker-compose.yml", "docker-compose.yaml"):
                    app_type = "docker_compose"
                    stored_path = os.path.relpath(os.path.join(root, fname), dst_dir)
                    break
                if lower == "dockerfile":
                    app_type = "docker"
                    break
            if app_type != "gradio":
                break

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO templates(id, name, type, path, description, vram_required) VALUES(?,?,?,?,?,?)",
        (
            template_id,
            name,
            app_type,
            stored_path,
            description or "",
            vram_required or 0,
        ),
    )
    conn.commit()
    conn.close()

    return {"template_id": template_id}


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

    app_path = os.path.join(UPLOAD_DIR, app_id)
    force_rmtree(app_path)

    log_file = os.path.join(LOG_DIR, f"{app_id}.log")
    if os.path.exists(log_file):
        os.remove(log_file)

    return {"detail": "deleted"}


class EditApp(BaseModel):
    app_id: str
    name: str
    description: str = ""


class EditTemplate(BaseModel):
    template_id: str
    name: str
    description: str = ""
    vram_required: int = 0


@app.post("/edit_app")
async def edit_app(info: EditApp, current_user: dict = Depends(get_current_user)):
    """Update app name and description."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM apps WHERE id=?", (info.app_id,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="app not found")
    c.execute(
        "SELECT id FROM apps WHERE name=? AND id!=?", (info.name.strip(), info.app_id)
    )
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="app name already exists")
    conn.close()
    save_status(
        info.app_id, name=info.name.strip(), description=info.description.strip()
    )
    return {"detail": "updated"}


@app.post("/edit_template")
async def edit_template(info: EditTemplate):
    """Update template metadata."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id FROM templates WHERE id=?", (info.template_id,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="template not found")
    c.execute(
        "SELECT id FROM templates WHERE name=? AND id!=?",
        (info.name.strip(), info.template_id),
    )
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="template name already exists")
    c.execute(
        "UPDATE templates SET name=?, description=?, vram_required=? WHERE id=?",
        (
            info.name.strip(),
            info.description.strip(),
            info.vram_required,
            info.template_id,
        ),
    )
    conn.commit()
    conn.close()
    return {"detail": "updated"}


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
            c.execute("UPDATE apps SET status='error', gpus=NULL WHERE id=?", (app_id,))
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
    c.execute("SELECT port FROM apps WHERE status='running' AND port IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    for row in rows:
        port = row[0]
        if port in AVAILABLE_PORTS:
            AVAILABLE_PORTS.remove(port)

    asyncio.create_task(cleanup_task())


# Example: run with `uvicorn backend.main:app --reload`


@app.get("/{path:path}", include_in_schema=False)
async def spa_fallback(path: str):
    """Serve index.html for client-side routes."""
    return FileResponse("frontend/index.html")
