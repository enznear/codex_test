"""Simple agent running on GPU server to build/run apps."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

app = FastAPI()

PROCESSES = {}

class RunRequest(BaseModel):
    app_id: str
    path: str
    type: str
    log_path: str

class StopRequest(BaseModel):
    app_id: str


def run_command(cmd, log_path, wait=True):
    """Run a command and optionally wait for completion."""
    with open(log_path, "a") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=log)
    if wait:
        process.wait()
        return process.returncode
    return process

@app.post("/run")
async def run_app(req: RunRequest):
    if req.type == "docker":
        build_cmd = ["docker", "build", "-t", req.app_id, req.path]
        ret = run_command(build_cmd, req.log_path)
        if ret != 0:
            requests.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "error"},
            )
            raise HTTPException(status_code=500, detail="build failed")
        run_cmd = ["docker", "run", "--rm", "--name", req.app_id, req.app_id]
        proc = run_command(run_cmd, req.log_path, False)
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
        proc = run_command(cmd, req.log_path, False)
    PROCESSES[req.app_id] = proc
    # report running status
    requests.post(f"{BACKEND_URL}/update_status", json={"app_id": req.app_id, "status": "running"})
    return {"detail": "started"}

@app.post("/stop")
async def stop_app(req: StopRequest):
    """Terminate a running app process if present."""
    proc = PROCESSES.pop(req.app_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    subprocess.run(["docker", "stop", req.app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    requests.post(f"{BACKEND_URL}/update_status", json={"app_id": req.app_id, "status": "stopped"})
    return {"detail": "stopped"}

# Example: run with `uvicorn agent.agent:app --port 8001`
