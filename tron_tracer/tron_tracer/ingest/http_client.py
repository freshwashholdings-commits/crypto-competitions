"""Shared rate-limited, retrying HTTP client with mandatory raw-response
archiving (blueprint Sec 3.4). Every response -- success or terminal
failure -- is written to `raw_api_responses` before the parsed body is
handed back to the caller, so the evidentiary chain (chain -> archived
API response -> normalized row) is unbroken even for responses that turn
out to be errors.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from tron_tracer.config import ClientConfig

ArchiveFn = Callable[[str, str, dict, int, str], int]
"""(source, endpoint, params, http_status, body) -> raw_response_id"""


class RateLimiter:
    """Simple token-bucket limiter, deterministic aside from wall-clock pacing
    (pacing never affects trace *output*, only ingestion speed)."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_call: float = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_call = time.monotonic()


@dataclass
class FetchResult:
    status: int
    body_text: str
    body_json: Any
    raw_response_id: int | None
    attempts: int


class RetryExhausted(RuntimeError):
    pass


class ApiClientBase:
    """Common request/retry/archive machinery for TronGrid and TronScan clients."""

    source_name: str = "unknown"

    def __init__(
        self,
        base_url: str,
        config: ClientConfig,
        archive_fn: ArchiveFn | None = None,
        api_key_header: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.archive_fn = archive_fn
        self._headers = {"Accept": "application/json"}
        if api_key_header and api_key:
            self._headers[api_key_header] = api_key
        self._limiter = RateLimiter(config.requests_per_second)
        self._client = httpx.Client(
            timeout=config.request_timeout_seconds,
            headers=self._headers,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def get(self, endpoint: str, params: dict | None = None) -> FetchResult:
        return self._request("GET", endpoint, params=params or {})

    def post(self, endpoint: str, json_body: dict | None = None) -> FetchResult:
        return self._request("POST", endpoint, json_body=json_body or {})

    def _request(self, method: str, endpoint: str, params: dict | None = None,
                 json_body: dict | None = None) -> FetchResult:
        url = f"{self.base_url}{endpoint}"
        attempts = 0
        last_exc: Exception | None = None
        archive_params = params if params is not None else (json_body or {})

        while attempts < self.config.max_retries:
            attempts += 1
            self._limiter.wait()
            try:
                resp = self._client.request(method, url, params=params, json=json_body)
            except httpx.TransportError as exc:
                last_exc = exc
                self._sleep_backoff(attempts)
                continue

            status = resp.status_code
            body_text = resp.text

            if status == 429 or 500 <= status < 600:
                if attempts >= self.config.max_retries:
                    break
                self._sleep_backoff(attempts)
                continue

            return self._finish(endpoint, archive_params, status, body_text)

        raise RetryExhausted(
            f"{self.source_name} {method} {endpoint} failed after {attempts} attempts"
            + (f"; last_status={status}" if "status" in dir() else "")
        ) from last_exc

    def _finish(self, endpoint: str, params: dict, status: int, body_text: str) -> FetchResult:
        raw_id = None
        if self.archive_fn is not None:
            raw_id = self.archive_fn(self.source_name, endpoint, params, status, body_text)

        try:
            body_json = json.loads(body_text) if body_text else None
        except json.JSONDecodeError:
            body_json = None

        return FetchResult(status=status, body_text=body_text, body_json=body_json, raw_response_id=raw_id, attempts=1)

    def _sleep_backoff(self, attempt: int) -> None:
        backoff = min(self.config.base_backoff_seconds * (2 ** (attempt - 1)), self.config.max_backoff_seconds)
        jitter = random.uniform(0, backoff * 0.25)
        time.sleep(backoff + jitter)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
