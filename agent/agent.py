"""Simple agent running on GPU server to build/run apps."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import requests
from typing import List, Optional
from proxy.proxy import add_route
import threading
import time

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

# store running processes keyed by app_id
processes = {}

app = FastAPI()

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

class StopRequest(BaseModel):
    app_id: str

def run_command(cmd, log_path, wait=True, env=None):
    """Run a command and optionally wait for completion."""
    with open(log_path, "a") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=log, env=env)
    if wait:
        process.wait()
        return process.returncode
    return process

@app.post("/run")
async def run_app(req: RunRequest, background_tasks: BackgroundTasks):
    # allocate a port and configure the proxy
    port = add_route(req.app_id, req.allow_ips, req.auth_header)
    if req.type == "docker":
        build_cmd = ["docker", "build", "-t", req.app_id, req.path]
        ret = run_command(build_cmd, req.log_path)
        if ret != 0:
            requests.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "error"},
            )
            raise HTTPException(status_code=500, detail="build failed")
        run_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            req.app_id,
            "-p",
            f"{port}:8000",
            req.app_id,
        ]
        background_tasks.add_task(run_command, run_cmd, req.log_path, False)

    else:  # gradio
        py_files = [f for f in os.listdir(req.path) if f.endswith(".py")]
        target = py_files[0] if py_files else None
        if not target:
            requests.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "error"},
            )
            raise HTTPException(status_code=400, detail="no python file")
        cmd = ["python", os.path.join(req.path, target)]
        env = os.environ.copy()
        env["PORT"] = str(port)
        background_tasks.add_task(run_command, cmd, req.log_path, False, env=env)
    # report running status
    requests.post(f"{BACKEND_URL}/update_status", json={"app_id": req.app_id, "status": "running"})

    return {"detail": "started"}


@app.post("/stop")
async def stop_app(req: StopRequest):
    info = processes.get(req.app_id)
    if not info:
        raise HTTPException(status_code=404, detail="app not running")
    if info["type"] == "docker":
        subprocess.run(["docker", "stop", req.app_id])
    else:
        info["process"].terminate()
    return {"detail": "stopping"}

# Example: run with `uvicorn agent.agent:app --port 8001`
