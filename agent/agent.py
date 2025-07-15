"""Simple agent running on GPU server to build/run apps."""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import subprocess
import os
import sys
import httpx
import asyncio
import socket
import threading
from typing import List, Optional, Dict
from proxy.proxy import add_route, remove_route, load_routes

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

app = FastAPI()

# Track running processes mapping app_id -> {"proc": process, "type": "docker"/"docker_tar"/"docker_compose"/"gradio"}

PROCESSES = {}

# Track reserved VRAM per GPU so concurrent deployments do not over allocate.
GPU_LOCK = threading.Lock()
GPU_USAGE: Dict[int, int] = {}


def reserve_gpus(usage: Dict[int, int]) -> None:
    """Increase reserved VRAM for the given GPU indices."""
    with GPU_LOCK:
        for idx, amount in usage.items():
            GPU_USAGE[idx] = GPU_USAGE.get(idx, 0) + amount


def release_gpus(usage: Dict[int, int]) -> None:
    """Decrease reserved VRAM for the given GPU indices."""
    with GPU_LOCK:
        for idx, amount in usage.items():
            remaining = GPU_USAGE.get(idx, 0) - amount
            if remaining > 0:
                GPU_USAGE[idx] = remaining
            else:
                GPU_USAGE.pop(idx, None)


def release_process_entry(app_id: str):
    """Remove process entry and free its GPUs."""
    entry = PROCESSES.pop(app_id, None)
    if entry:
        gpus = entry.get("gpus") or []
        vram = entry.get("vram_required") or 0
        if gpus:
            usage = {idx: vram for idx in gpus}
            release_gpus(usage)
    return entry


async def _cleanup_deleted_app(app_id: str):
    """Terminate running process and remove proxy route if backend deleted the app."""
    entry = release_process_entry(app_id)
    if entry:
        proc = entry.get("proc")
        app_type = entry.get("type")
        if proc is not None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 30)
                except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                    proc.kill()
                except Exception:
                    proc.kill()
            except Exception:
                pass
        if app_type in ("docker", "docker_tar"):
            subprocess.run(["docker", "stop", app_id], check=False)
        elif app_type == "docker_compose":
            subprocess.run(["docker", "compose", "-p", app_id, "down"], check=False)
    remove_route(app_id)


@app.on_event("startup")
async def recover_running_apps():
    """Detect running apps and restart heartbeat loops."""
    # Load existing proxy routes to discover app IDs
    routes = load_routes()
    # Query backend for app statuses to get GPU assignments if available
    status_map = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/status", timeout=5)
            resp.raise_for_status()
            for info in resp.json():
                status_map[info.get("id")] = info
    except Exception:
        pass

    for app_id, info in routes.items():
        # Skip if already tracked
        if app_id in PROCESSES:
            continue

        is_docker = False
        container_running = False
        try:
            out = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Running}}", app_id],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            is_docker = True
            container_running = out == "true"
        except Exception:
            pass

        port_running = False
        port = info.get("port")
        if port:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(1)
                port_running = s.connect_ex(("127.0.0.1", port)) == 0
            finally:
                s.close()

        if container_running or port_running:
            status = status_map.get(app_id, {})
            gpus = status.get("gpus")
            vram_required = status.get("vram_required", 0)
            PROCESSES[app_id] = {
                "proc": None,
                "type": "docker" if is_docker else "gradio",
                "gpus": gpus,
                "vram_required": vram_required,
            }
            if gpus:
                usage = {idx: vram_required for idx in gpus}
                reserve_gpus(usage)
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": app_id, "status": "running", "gpus": gpus},
                        timeout=5,
                    )
            except Exception:
                pass
            asyncio.create_task(heartbeat_loop(app_id))
        else:
            # Stale route with no running process
            remove_route(app_id)

def get_available_gpu(required: int = 0) -> Optional[List[int]]:

    """Return GPUs that have enough free memory for ``required`` MB."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            encoding="utf-8",
        )

        info = []
        for line in output.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 3:
                continue
            idx = int(parts[0])
            total = int(parts[1])
            used_mem = int(parts[2])
            info.append((idx, total, used_mem))

        if not info:
            return None

        with GPU_LOCK:
            candidates = []
            for idx, total, used_mem in info:
                free = total - used_mem - GPU_USAGE.get(idx, 0)
                if free > 0:
                    candidates.append((idx, free))

            if not candidates:
                return None

            # sort by index for deterministic allocation
            candidates.sort(key=lambda t: t[0])

            if required <= 0:
                return [candidates[0][0]]

            # try single GPU first
            for idx, free in candidates:
                if free >= required:
                    GPU_USAGE[idx] = GPU_USAGE.get(idx, 0) + required
                    return [idx]

            # attempt multi-GPU allocation
            allocation: Dict[int, int] = {}
            remaining = required
            for idx, free in candidates:
                if remaining <= 0:
                    break
                take = min(remaining, free)
                allocation[idx] = take
                remaining -= take

            if remaining <= 0:
                reserve_gpus(allocation)
                return list(allocation.keys())

            # otherwise insufficient memory
            return None

    except Exception:
        return None


class RunRequest(BaseModel):
    app_id: str
    path: str
    type: str
    log_path: str
    allow_ips: Optional[List[str]] = None
    auth_header: Optional[str] = None
    port: int
    reuse_image: bool = False
    gpus: Optional[List[int]] = None
    vram_required: int = 0



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


async def async_run_wait(cmd, log_path, env=None, cwd=None):
    """Run a command asynchronously and wait for it to finish."""
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=log, stderr=log, env=env_vars, cwd=cwd
        )
        await proc.wait()
        return proc.returncode


async def async_run_detached(cmd, log_path, env=None, cwd=None):
    """Run a command asynchronously without waiting."""
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=log, stderr=log, env=env_vars, cwd=cwd
        )
    return proc

@app.post("/run")
async def run_app(req: RunRequest, background_tasks: BackgroundTasks):
    # configure the proxy for the assigned port and start build/run in background
    add_route(req.app_id, req.port, req.allow_ips, req.auth_header)
    gpus = get_available_gpu(req.vram_required)
    if gpus is None:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error", "gpus": None},
                    timeout=5,
                )
        except Exception:
            pass
        remove_route(req.app_id)
        raise HTTPException(status_code=500, detail="No available GPU")

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "building", "gpus": gpus},
                timeout=5,
            )
    except Exception:
        pass
    req.gpus = gpus  # type: ignore
    PROCESSES[req.app_id] = {
        "proc": None,
        "type": req.type,
        "gpus": gpus,
        "vram_required": req.vram_required,
    }
    background_tasks.add_task(build_and_run, req)
    return {"detail": "building"}


@app.post("/restart")
async def restart_app(req: RunRequest, background_tasks: BackgroundTasks):
    """Restart an app using an existing Docker image."""
    req.reuse_image = True
    add_route(req.app_id, req.port, req.allow_ips, req.auth_header)
    gpus = get_available_gpu(req.vram_required)
    if gpus is None:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error", "gpus": None},
                    timeout=5,
                )
        except Exception:
            pass
        remove_route(req.app_id)
        raise HTTPException(status_code=500, detail="No available GPU")

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "building", "gpus": gpus},
                timeout=5,
            )
    except Exception:
        pass
    req.gpus = gpus  # type: ignore
    PROCESSES[req.app_id] = {
        "proc": None,
        "type": req.type,
        "gpus": gpus,
        "vram_required": req.vram_required,
    }
    background_tasks.add_task(build_and_run, req)
    return {"detail": "restarting"}


async def wait_for_http_ready(app_id: str, port: int, proc):
    """Poll the app until an HTTP response is received then mark running."""
    url = f"http://127.0.0.1:{port}/"
    while proc.returncode is None:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(url, timeout=1)
                entry = PROCESSES.get(app_id)
                gpus = entry.get("gpus") if entry else None
                resp = await client.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": app_id, "status": "running", "gpus": gpus},
                    timeout=5,
                )
                if resp.status_code == 404:
                    await _cleanup_deleted_app(app_id)
                    return
                return
        except Exception:
            await asyncio.sleep(1)


async def build_and_run(req: RunRequest):
    """Build docker image if needed then run the app."""
    gpus = req.gpus if req.gpus is not None else get_available_gpu(req.vram_required)
    if gpus is None:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error", "gpus": None},
                    timeout=5,
                )
        finally:
            remove_route(req.app_id)
            release_process_entry(req.app_id)
        return

    if not is_port_free(req.port):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BACKEND_URL}/update_status",
                    json={"app_id": req.app_id, "status": "error", "gpus": None},
                    timeout=5,
                )
        finally:
            remove_route(req.app_id)
            release_process_entry(req.app_id)
        return
    env = {
        "PORT": str(req.port),
        "ROOT_PATH": f"/apps/{req.app_id}",
    }

    token = os.environ.get("HUGGINGFACE_HUB_TOKEN")
    hf_token = os.environ.get("HF_TOKEN")
    if token:
        env["HUGGINGFACE_HUB_TOKEN"] = token
    if hf_token:
        env["HF_TOKEN"] = hf_token
    token_value = token or hf_token


    if req.type == "docker":
        if not req.reuse_image:
            build_cmd = ["docker", "build", "--network", "host", "-t", req.app_id, req.path]
            ret = await async_run_wait(build_cmd, req.log_path)
            if ret != 0:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{BACKEND_URL}/update_status",
                            json={"app_id": req.app_id, "status": "error"},
                            timeout=5,
                        )
                finally:
                    remove_route(req.app_id)
                    release_process_entry(req.app_id)
                return
        run_cmd = [
            "docker",
            "run",
            "--rm",
        ]
        if gpus:
            run_cmd += ["--gpus", f"device={','.join(map(str, gpus))}"]
        run_cmd += [

            "-p",
            f"{req.port}:{req.port}",
            "-e",
            f"PORT={req.port}",
        ]

        if token_value:
            run_cmd += ["-e", f"HUGGINGFACE_HUB_TOKEN={token_value}"]

        run_cmd += [
            "-e",
            f"ROOT_PATH=/apps/{req.app_id}",
            "--name",
            req.app_id,
            req.app_id,
        ]
        proc = await async_run_detached(run_cmd, req.log_path, env=env)
    elif req.type == "docker_compose":
        compose_file = os.path.join(req.path, "docker-compose.yml")
        if not os.path.exists(compose_file):
            compose_file = os.path.join(req.path, "docker-compose.yaml")
        if not os.path.exists(compose_file):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": req.app_id, "status": "error"},
                        timeout=5,
                    )
            finally:
                remove_route(req.app_id)
                release_process_entry(req.app_id)
            return
        cmd = [
            "docker",
            "compose",
            "-f",
            compose_file,
            "-p",
            req.app_id,
            "up",
            "--build",
            "-d",
        ]
        ret = await async_run_wait(cmd, req.log_path, env=env)
        if ret != 0:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": req.app_id, "status": "error"},
                        timeout=5,
                    )
            finally:
                remove_route(req.app_id)
            release_process_entry(req.app_id)
            return
        proc = None
    elif req.type == "docker_tar":
        run_image = req.app_id
        if not req.reuse_image:
            image_tag = None
            try:
                import tarfile, json

                with tarfile.open(req.path) as tf:
                    mf = tf.extractfile("manifest.json")
                    if mf:
                        manifest = json.load(mf)
                        tags = manifest[0].get("RepoTags")
                        if tags:
                            image_tag = tags[0]
                        else:
                            cfg = manifest[0].get("Config")
                            if cfg:
                                image_tag = cfg.split(".")[0]
            except Exception:
                image_tag = None

            load_cmd = ["docker", "load", "-i", req.path]
            ret = await async_run_wait(load_cmd, req.log_path)
            if ret != 0:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{BACKEND_URL}/update_status",
                            json={"app_id": req.app_id, "status": "error"},
                            timeout=5,
                        )
                finally:
                    remove_route(req.app_id)
                    release_process_entry(req.app_id)
                return

            if image_tag:
                await async_run_wait(["docker", "tag", image_tag, req.app_id], req.log_path)
        run_cmd = [
            "docker",
            "run",
            "--rm",
        ]
        if gpus:
            run_cmd += ["--gpus", f"device={','.join(map(str, gpus))}"]
        run_cmd += [

            "-p",
            f"{req.port}:{req.port}",
            "-e",
            f"PORT={req.port}",
        ]

        if token_value:
            run_cmd += ["-e", f"HUGGINGFACE_HUB_TOKEN={token_value}"]

        run_cmd += [
            "-e",
            f"ROOT_PATH=/apps/{req.app_id}",
            "--name",
            req.app_id,
            run_image,
        ]
        proc = await async_run_detached(run_cmd, req.log_path, env=env)
    else:  # gradio
        py_files = [f for f in os.listdir(req.path) if f.endswith(".py")]
        if "app.py" in py_files:
            target = "app.py"
        else:
            target = py_files[0] if py_files else None
        if not target:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": req.app_id, "status": "error"},
                        timeout=5,
                    )
            finally:
                remove_route(req.app_id)
                release_process_entry(req.app_id)
            return

        if gpus:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, gpus))

        venv_dir = os.path.join(req.path, "venv")
        python_exe = sys.executable
        ret = await async_run_wait(
            [python_exe, "-m", "venv", "venv"], req.log_path, cwd=req.path
        )
        if ret != 0:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": req.app_id, "status": "error"},
                        timeout=5,
                    )
            finally:
                remove_route(req.app_id)
                release_process_entry(req.app_id)
            return

        req_file = os.path.join(req.path, "requirements.txt")
        if os.path.exists(req_file):
            python_path = os.path.join("venv", "bin", "python")
            ret = await async_run_wait(
                [python_path, "-m", "pip", "install", "-r", "requirements.txt"],

                req.log_path,
                env=env,
                cwd=req.path,
            )
            if ret != 0:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{BACKEND_URL}/update_status",
                            json={"app_id": req.app_id, "status": "error"},
                            timeout=5,
                        )
                finally:
                    remove_route(req.app_id)
                    release_process_entry(req.app_id)
                return

        python_path = os.path.join("venv", "bin", "python")
        cmd = [python_path, target]

        proc = await async_run_detached(cmd, req.log_path, env=env, cwd=req.path)

    # Store the process along with the type so that cleanup can behave
    # differently for docker vs gradio apps
    PROCESSES[req.app_id] = {"proc": proc, "type": req.type, "gpus": gpus, "vram_required": req.vram_required}
    asyncio.create_task(heartbeat_loop(req.app_id))
    if req.type == "docker_compose":
        asyncio.create_task(wait_for_compose_ready(req.app_id, req.port))
    else:
        asyncio.create_task(wait_for_http_ready(req.app_id, req.port, proc))


async def wait_for_port(app_id: str, port: int, proc):
    """Wait until the given port accepts connections then mark running."""
    while proc.returncode is None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{BACKEND_URL}/update_status",
                            json={"app_id": app_id, "status": "running"},
                            timeout=5,
                        )
                except Exception:
                    pass
                return
        finally:
            s.close()
        await asyncio.sleep(1)

async def wait_for_compose_ready(app_id: str, port: int):
    """Wait for compose service port to open and mark running."""
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f"{BACKEND_URL}/update_status",
                            json={"app_id": app_id, "status": "running"},
                            timeout=5,
                        )
                        if resp.status_code == 404:
                            await _cleanup_deleted_app(app_id)
                            return
                except Exception:
                    pass
                return
        finally:
            s.close()
        await asyncio.sleep(1)

async def heartbeat_loop(app_id: str):
    """Send periodic heartbeats and detect process exit."""
    while True:
        entry = PROCESSES.get(app_id)
        if not entry:
            break

        proc = entry.get("proc")
        app_type = entry.get("type")

        running = True
        status = "error"
        if proc is not None:
            if proc.returncode is not None:
                running = False
                status = "finished" if proc.returncode == 0 else "error"
        else:
            if app_type in ("docker", "docker_tar"):
                try:
                    out = subprocess.check_output(
                        ["docker", "inspect", "-f", "{{.State.Running}}", app_id],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                    running = out == "true"
                    if not running:
                        exit_code = subprocess.check_output(
                            ["docker", "inspect", "-f", "{{.State.ExitCode}}", app_id],
                            text=True,
                            stderr=subprocess.DEVNULL,
                        ).strip()
                        status = "finished" if exit_code == "0" else "error"
                        subprocess.run(["docker", "rm", app_id], check=False)
                except Exception:
                    running = False
                    status = "error"
            elif app_type == "docker_compose":
                try:
                    ids = subprocess.check_output(
                        ["docker", "compose", "-p", app_id, "ps", "-q"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip().splitlines()
                    running = False
                    for cid in ids:
                        state = subprocess.check_output(
                            ["docker", "inspect", "-f", "{{.State.Running}}", cid],
                            text=True,
                            stderr=subprocess.DEVNULL,
                        ).strip()
                        if state == "true":
                            running = True
                            break
                    if not running:
                        status = "finished"
                except Exception:
                    running = False
                    status = "error"
            else:
                route = load_routes().get(app_id)
                if route:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        s.settimeout(1)
                        running = s.connect_ex(("127.0.0.1", route["port"])) == 0
                    finally:
                        s.close()
                else:
                    running = False
                    status = "error"

        if not running:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{BACKEND_URL}/update_status",
                        json={"app_id": app_id, "status": status, "gpus": None},
                        timeout=5,
                    )
                    if resp.status_code == 404:
                        await _cleanup_deleted_app(app_id)
                        break
            except Exception:
                pass
            remove_route(app_id)
            release_process_entry(app_id)
            break

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{BACKEND_URL}/heartbeat",
                    json={"app_id": app_id},
                    timeout=5,
                )
                if resp.status_code == 404:
                    await _cleanup_deleted_app(app_id)
                    break
        except Exception:
            pass

        await asyncio.sleep(5)


@app.post("/stop")
async def stop_app(req: StopRequest):
    """Stop a running app process."""
    entry = PROCESSES.get(req.app_id)
    if not entry:
        raise HTTPException(status_code=404, detail="app not running")
    proc = entry.get("proc")
    app_type = entry.get("type")

    if proc is not None:
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 30)
            except (asyncio.TimeoutError, subprocess.TimeoutExpired):
                proc.kill()
            except Exception:
                proc.kill()
        except Exception:
            pass

    release_process_entry(req.app_id)

    # Best effort stop docker container for docker-based apps
    if app_type in ("docker", "docker_tar"):
        subprocess.run(["docker", "stop", req.app_id], check=False)
    elif app_type == "docker_compose":
        subprocess.run(["docker", "compose", "-p", req.app_id, "down"], check=False)

    # Remove proxy route and notify backend
    remove_route(req.app_id)

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/update_status",
                json={"app_id": req.app_id, "status": "stopped", "gpus": None},
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
