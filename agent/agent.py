"""Simple agent running on GPU server to build/run apps."""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import subprocess
import os
import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

app = FastAPI()

class RunRequest(BaseModel):
    app_id: str
    path: str
    type: str
    log_path: str


def run_command(cmd, log_path, wait=True):
    """Run a command and optionally wait for completion."""
    with open(log_path, "a") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=log)
    if wait:
        process.wait()
        return process.returncode
    return process.pid

@app.post("/run")
async def run_app(req: RunRequest, background_tasks: BackgroundTasks):
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
        background_tasks.add_task(run_command, cmd, req.log_path, False)
    # report running status
    requests.post(f"{BACKEND_URL}/update_status", json={"app_id": req.app_id, "status": "running"})
    return {"detail": "started"}

# Example: run with `uvicorn agent.agent:app --port 8001`
