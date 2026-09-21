"""Security event logging.

One structured line per event: ``name key=value ...`` at INFO, or WARNING for
failures. Never log a plaintext email address or password — hash the email
with ``hash_email`` first.
"""

from __future__ import annotations

import hashlib
import logging

security = logging.getLogger("lp.security")


def hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def event(name: str, level: int = logging.INFO, **fields) -> None:
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    security.log(level, f"{name} {parts}".rstrip())
