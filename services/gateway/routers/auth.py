"""Shared auth dependency for gateway routers."""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

from local_system.config import get_settings

settings = get_settings()
_api_key = os.environ.get("API_SECRET_KEY", settings.api_secret_key)


def verify_api_key(request: Request) -> None:
    """Check API key if one is configured (skip if set to 'changeme'/dev mode)."""
    if _api_key == "changeme":
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_api_key}" and request.query_params.get("api_key") != _api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
