"""Thin HTTP client for the TCGAPIs v2 API (https://tcgapis.com/documentation).

Endpoint chain used by this app:
    GET /api/v2/games                     -> categoryId per game
    GET /api/v2/cards/:groupId            -> cards in an expansion (productId, name, number...)
    GET /api/v1/catalog/...               -> search catalog by name  (Hobby+)
    GET /api/v2/sales-history/:productId  -> recent completed sales   (Business+)
    GET /api/v2/prices/:productId         -> market/low/mid/high      (Business+)

Auth: x-api-key header.

NOTE: TCGAPIs response shapes can evolve. The parsing in the identity/price
providers is defensive and centralized so you only adjust field names in one place.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from utils.logger import get_logger

log = get_logger("tcgapis")


class TCGAPIsError(RuntimeError):
    pass


class TCGAPIsClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 8.0, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"x-api-key": api_key, "Accept": "application/json"})

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    # rate limited -- back off and retry
                    time.sleep(min(2 ** attempt, 5))
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                log.warning("TCGAPIs GET %s failed: %s", path, exc)
                raise TCGAPIsError(str(exc)) from exc
        raise TCGAPIsError(str(last_exc) if last_exc else "unknown error")
