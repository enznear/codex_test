"""Simple agent running on GPU server to build/run apps."""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import subprocess
import os
import sys
import requests
import asyncio
import socket
from typing import List, Optional
from proxy.proxy import add_route, remove_route
import threading
import time

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

app = FastAPI()

# Track running processes mapping app_id -> {"proc": process, "type": "docker"/"gradio"}

PROCESSES = {}

class RunRequest(BaseModel):
    app_id: str
    path: str
    type: str
    log_path: str
    allow_ips: Optional[List[str]] = None
    auth_header: Optional[str] = None
    port: int



class StopRequest(BaseModel):
    app_id: str

class RemoveRouteRequest(BaseModel):
    app_id: str

def is_port_free(port: int) -> bool:
    """Check whether a port can be bound."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()

def run_command(cmd, log_path, wait=True, env=None):
    """Run a command and optionally wait for completion."""
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=log, env=env_vars)

    if wait:
        process.wait()
        return process.returncode
    return process


async def async_run_wait(cmd, log_path, env=None):
    """Run a command asynchronously and wait for it to finish."""
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=log, stderr=log, env=env_vars)
        await proc.wait()
        return proc.returncode


async def async_run_detached(cmd, log_path, env=None):
    """Run a command asynchronously without waiting."""
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=log, stderr=log, env=env_vars)
    return proc

@app.post("/run")
async def run_app(req: RunRequest, background_tasks: BackgroundTasks):
    # configure the proxy for the assigned port and start build/run in background
    add_route(req.app_id, req.port, req.allow_ips, req.auth_header)
    background_tasks.add_task(build_and_run, req)
    return {"detail": "building"}


async def build_and_run(req: RunRequest):
    """Build docker image if needed then run the app."""
    if not is_port_free(req.port):
        try:
            requests.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "error"},
                timeout=5,
            )
        finally:
            remove_route(req.app_id)
        return
    if req.type == "docker":
        build_cmd = ["docker", "build", "-t", req.app_id, req.path]
        ret = await async_run_wait(build_cmd, req.log_path)
        if ret != 0:
            try:
                requests.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error"},
                    timeout=5,
                )
            finally:
                remove_route(req.app_id)
            return
        run_cmd = [
            "docker",
            "run",
            "--rm",
            "-p",
            f"{req.port}:{req.port}",
            "-e",
            f"PORT={req.port}",
            "--name",
            req.app_id,
            req.app_id,
        ]
        proc = await async_run_detached(run_cmd, req.log_path, env={"PORT": str(req.port)})
    else:  # gradio
        py_files = [f for f in os.listdir(req.path) if f.endswith(".py")]
        target = py_files[0] if py_files else None
        if not target:
            try:
                requests.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error"},
                    timeout=5,
                )
            finally:
                remove_route(req.app_id)
            return
        cmd = [sys.executable, os.path.join(req.path, target)]
        proc = await async_run_detached(cmd, req.log_path, env={"PORT": str(req.port)})

    # Store the process along with the type so that cleanup can behave
    # differently for docker vs gradio apps
    PROCESSES[req.app_id] = {"proc": proc, "type": req.type}
    asyncio.create_task(heartbeat_loop(req.app_id))

    try:
        requests.post(
            f"{BACKEND_URL}/update_status",
            json={"app_id": req.app_id, "status": "running"},
            timeout=5,
        )
    except Exception:
        pass



async def heartbeat_loop(app_id: str):
    """Send periodic heartbeats and detect process exit."""
    entry = PROCESSES.get(app_id)
    proc = entry["proc"] if entry else None
    while proc:
        if proc.returncode is not None:
            status = "finished" if proc.returncode == 0 else "error"
            try:
                requests.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": app_id, "status": status},
                    timeout=5,
                )
            except Exception:
                pass
            # Clean up Nginx routing for this app
            remove_route(app_id)
            PROCESSES.pop(app_id, None)
            break
        try:
            requests.post(
                f"{BACKEND_URL}/heartbeat",
                json={"app_id": app_id},
                timeout=5,
            )
        except Exception:
            pass
        await asyncio.sleep(5)
        entry = PROCESSES.get(app_id)
        proc = entry["proc"] if entry else None


@app.post("/stop")
async def stop_app(req: StopRequest):
    """Stop a running app process."""
    entry = PROCESSES.get(req.app_id)
    if not entry:
        raise HTTPException(status_code=404, detail="app not running")
    proc = entry["proc"]
    app_type = entry.get("type")

    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            proc.kill()
        except Exception:
            proc.kill()
    except Exception:
        pass

    PROCESSES.pop(req.app_id, None)

    # Best effort stop docker container only if the app used docker
    if app_type == "docker":
        subprocess.run(["docker", "stop", req.app_id], check=False)

    # Remove proxy route and notify backend
    remove_route(req.app_id)

    try:
        requests.post(
            f"{BACKEND_URL}/update_status",
            json={"app_id": req.app_id, "status": "finished"},
            timeout=5,
        )
    except Exception:
        pass

    return {"detail": "stopped"}


@app.post("/remove_route")
async def remove_route_endpoint(req: RemoveRouteRequest):
    """Remove an app's proxy route regardless of process state."""
    remove_route(req.app_id)
    return {"detail": "removed"}


# Example: run with `uvicorn agent.agent:app --port 8001`
