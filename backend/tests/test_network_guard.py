"""The test suite must never reach the network; pytest-socket enforces it."""

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_inet_socket_creation_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_outbound_connection_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("192.0.2.1", 443), timeout=0.1)
