"""Default unit isolation: never load dotenv or use real network/native DB I/O."""
import os
import socket

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch, request):
    """Unit adapters are doubles; opt-in integration installs its own strict guard."""
    if request.node.get_closest_marker("integration"):
        return
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected live network/database call in isolated unit suite")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", blocked)
