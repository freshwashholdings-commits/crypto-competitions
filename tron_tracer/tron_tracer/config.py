from __future__ import annotations

import os
from dataclasses import dataclass, field

TRX_ASSET_ID = "TRX"
SUN_PER_TRX = 1_000_000

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_TRC20_DECIMALS = 6

TRONGRID_BASE_URL = os.environ.get("TRONGRID_BASE_URL", "https://api.trongrid.io")
TRONSCAN_BASE_URL = os.environ.get("TRONSCAN_BASE_URL", "https://apilist.tronscanapi.com")


@dataclass(frozen=True)
class ClientConfig:
    """Ingestion client configuration. All values overridable via env/CLI."""

    trongrid_base_url: str = TRONGRID_BASE_URL
    tronscan_base_url: str = TRONSCAN_BASE_URL
    trongrid_api_key: str | None = field(default_factory=lambda: os.environ.get("TRONGRID_API_KEY"))
    tronscan_api_key: str | None = field(default_factory=lambda: os.environ.get("TRONSCAN_API_KEY"))
    max_retries: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    requests_per_second: float = 10.0
    page_limit: int = 200
    request_timeout_seconds: float = 30.0


DEFAULT_DB_URL = os.environ.get("TRON_TRACER_DB_URL", "sqlite:///tron_tracer_case.db")
