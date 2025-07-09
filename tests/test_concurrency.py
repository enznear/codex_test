import asyncio
import importlib.util
from pathlib import Path
import sys
import types

sys.modules.setdefault("httpx", types.ModuleType("httpx"))
# Minimal FastAPI stub to avoid heavy dependencies during import
fastapi_mod = types.ModuleType("fastapi")

class _FastAPI:
    def __init__(self, *a, **k):
        pass
    def post(self, *a, **k):
        def wrapper(f):
            return f
        return wrapper
    def get(self, *a, **k):
        def wrapper(f):
            return f
        return wrapper
    def delete(self, *a, **k):
        def wrapper(f):
            return f
        return wrapper
    def on_event(self, *a, **k):
        def wrapper(f):
            return f
        return wrapper
    def mount(self, *a, **k):
        pass

class _UploadFile:
    pass

def _File(*a, **k):
    pass

class _HTTPException(Exception):
    def __init__(self, *a, **k):
        pass

def _Form(*a, **k):
    pass

class _BackgroundTasks:
    pass

def _Depends(*a, **k):
    pass

class _status:
    HTTP_401_UNAUTHORIZED = 401

fastapi_mod.FastAPI = _FastAPI
fastapi_mod.UploadFile = _UploadFile
fastapi_mod.File = _File
fastapi_mod.HTTPException = _HTTPException
fastapi_mod.Form = _Form
fastapi_mod.BackgroundTasks = _BackgroundTasks
fastapi_mod.Depends = _Depends
fastapi_mod.status = _status
sys.modules.setdefault("fastapi", fastapi_mod)
sys.modules.setdefault("fastapi.responses", types.ModuleType("fastapi.responses"))
sys.modules["fastapi.responses"].PlainTextResponse = object
sys.modules["fastapi.responses"].FileResponse = object
sys.modules.setdefault("fastapi.staticfiles", types.ModuleType("fastapi.staticfiles"))
class _StaticFiles:
    def __init__(self, *a, **k):
        pass
sys.modules["fastapi.staticfiles"].StaticFiles = _StaticFiles
sys.modules.setdefault("fastapi.security", types.ModuleType("fastapi.security"))
sys.modules["fastapi.security"].OAuth2PasswordBearer = lambda *a, **k: None
sys.modules["fastapi.security"].OAuth2PasswordRequestForm = object
sys.modules.setdefault("passlib", types.ModuleType("passlib"))
context_mod = types.ModuleType("passlib.context")
class DummyCryptContext:
    def __init__(self, *a, **k):
        pass
    def hash(self, pw):
        return "hashed" + pw
    def verify(self, pw, hashed):
        return True
context_mod.CryptContext = DummyCryptContext
sys.modules.setdefault("passlib.context", context_mod)
jose_mod = types.ModuleType("jose")
class _JWTError(Exception):
    pass
jose_mod.JWTError = _JWTError
jose_mod.jwt = types.SimpleNamespace(encode=lambda *a, **k: "", decode=lambda *a, **k: {})
sys.modules.setdefault("jose", jose_mod)
sys.modules.setdefault("jose.jwt", jose_mod.jwt)
sys.modules.setdefault("multipart", types.ModuleType("multipart"))

spec = importlib.util.spec_from_file_location(
    "backend.main",
    Path(__file__).resolve().parents[1] / "backend" / "main.py",
)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)

async def allocate_port():
    # mimic port allocation logic from upload_app/deploy_template
    with main.PORT_LOCK:
        if not main.AVAILABLE_PORTS:
            return None
        port = None
        while main.AVAILABLE_PORTS:
            candidate = main.AVAILABLE_PORTS.pop()
            port = candidate if main.is_port_free(candidate) else None
            if port is not None:
                break
        if port is None:
            return None
        return port

def test_concurrent_allocations(monkeypatch):
    # reduce port range for test
    original_ports = main.AVAILABLE_PORTS.copy()
    main.AVAILABLE_PORTS = set(range(10000, 10010))

    monkeypatch.setattr(main, "is_port_free", lambda p: True)

    async def run_tasks():
        tasks = [allocate_port() for _ in range(5)]
        return await asyncio.gather(*tasks)

    ports = asyncio.run(run_tasks())

    assert len(ports) == len(set(ports))

    # restore
    main.AVAILABLE_PORTS = original_ports

