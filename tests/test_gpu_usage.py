import os
import sys
import types
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Provide a minimal httpx stub so agent can be imported without the dependency
httpx_stub = types.ModuleType("httpx")
class DummyAsyncClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass
    async def get(self, *args, **kwargs):
        return types.SimpleNamespace(json=lambda: [], raise_for_status=lambda: None, status_code=200)
    async def post(self, *args, **kwargs):
        return types.SimpleNamespace(status_code=200)

httpx_stub.AsyncClient = DummyAsyncClient
sys.modules.setdefault("httpx", httpx_stub)

import agent.agent as agent

# Helper to patch subprocess.check_output for nvidia-smi
class DummySubprocess:
    def __init__(self, output):
        self.output = output

    def check_output(self, *args, **kwargs):
        return self.output

def reset_state():
    agent.GPU_USAGE.clear()
    agent.PROCESSES.clear()


def test_partial_allocation(monkeypatch):
    output = "0, 10000, 2000\n1, 10000, 2000\n"
    dummy = DummySubprocess(output)
    monkeypatch.setattr(agent, 'subprocess', dummy)
    reset_state()

    gpus = agent.get_available_gpu(2000)
    assert gpus == [0]
    assert agent.GPU_USAGE[0] == 2000

    gpus = agent.get_available_gpu(7000)
    assert gpus == [1]
    assert agent.GPU_USAGE[1] == 7000

    agent.release_gpus({0: 2000})
    assert agent.GPU_USAGE.get(0, 0) == 0


def test_release_process_entry(monkeypatch):
    output = "0, 10000, 2000\n"
    dummy = DummySubprocess(output)
    monkeypatch.setattr(agent, 'subprocess', dummy)
    reset_state()

    gpus = agent.get_available_gpu(4000)
    assert gpus == [0]
    agent.PROCESSES['app'] = {
        'proc': None,
        'type': 'docker',
        'gpus': gpus,
        'vram_required': 4000,
    }
    assert agent.GPU_USAGE[0] == 4000

    agent.release_process_entry('app')
    assert agent.GPU_USAGE.get(0, 0) == 0
    assert 'app' not in agent.PROCESSES


def test_multi_gpu_allocation(monkeypatch):
    output = "0, 40000, 1000\n1, 40000, 1000\n"
    dummy = DummySubprocess(output)
    monkeypatch.setattr(agent, 'subprocess', dummy)
    reset_state()

    gpus = agent.get_available_gpu(60000)
    assert gpus == [0, 1]
    assert agent.GPU_USAGE[0] == 39000
    assert agent.GPU_USAGE[1] == 21000
