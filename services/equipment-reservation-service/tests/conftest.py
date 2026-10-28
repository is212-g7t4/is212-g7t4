"""Reservation unit isolation: dotenv disabled and external sockets blocked."""
import os
import socket

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    """Tests must explicitly replace every external adapter with a local double."""
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected live network/database call in isolated unit suite")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
