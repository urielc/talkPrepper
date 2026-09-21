"""Test-wide fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_secret_key():
    """Every test run gets its own throwaway Fernet key via ``LP_SECRET_KEY``, so
    no test ever creates or reads ``data/secret.key`` in the real project data
    directory (the one the LAN instance uses)."""
    from cryptography.fernet import Fernet
    os.environ["LP_SECRET_KEY"] = Fernet.generate_key().decode()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets():
    """``server.auth._buckets`` is process-global and would otherwise carry
    login/email attempt counts from one test into the next (every test's
    TestClient shares the same fallback client IP)."""
    from server import auth as auth_mod
    auth_mod._buckets.clear()
    yield
    auth_mod._buckets.clear()
