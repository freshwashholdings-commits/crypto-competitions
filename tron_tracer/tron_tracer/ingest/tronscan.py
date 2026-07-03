"""TronScan client (blueprint Sec 3.1). Used only for two purposes: (1) a
convenience cross-check on activation info, and (2) public address
labels. Labels are *leads, not evidence* -- always stored with
source='tronscan' and a retrieval timestamp (blueprint Sec 6.1 label
whitelist requirement / Sec 10 label-quality limitation).

Endpoint paths below should be re-verified against
https://apilist.tronscanapi.com/api/docs before production use -- this
is a third-party convenience API, not part of the evidentiary chain, so
a stale field name degrades label quality rather than trace correctness.
"""

from __future__ import annotations

from tron_tracer.config import ClientConfig
from tron_tracer.ingest.http_client import ApiClientBase, ArchiveFn


class TronScanClient(ApiClientBase):
    source_name = "tronscan"

    def __init__(self, config: ClientConfig, archive_fn: ArchiveFn | None = None, transport=None):
        super().__init__(
            base_url=config.tronscan_base_url,
            config=config,
            archive_fn=archive_fn,
            api_key_header="TRON-PRO-API-KEY",
            api_key=config.tronscan_api_key,
            transport=transport,
        )

    def get_account_detail(self, address: str) -> tuple[dict | None, int | None]:
        result = self.get("/api/accountv2", params={"address": address})
        return (result.body_json or None), result.raw_response_id

    def extract_labels(self, address: str, detail: dict | None) -> list[dict]:
        """Best-effort extraction of publicly displayed tags/labels.
        TronScan's public tag fields have shifted across API versions
        (`publicTag`, `accountType`, `tags`); check all known aliases."""
        if not detail:
            return []
        labels: list[dict] = []
        public_tag = detail.get("publicTag") or detail.get("public_tag")
        if public_tag:
            labels.append({"address": address, "label": public_tag, "category": "public_tag", "source": "tronscan"})
        account_type = detail.get("accountType") or detail.get("account_type")
        if account_type and account_type not in ("normal", "Normal"):
            labels.append({"address": address, "label": account_type, "category": account_type.lower(), "source": "tronscan"})
        for tag in detail.get("tags") or []:
            name = tag.get("name") if isinstance(tag, dict) else tag
            if name:
                labels.append({"address": address, "label": name, "category": "tag", "source": "tronscan"})
        return labels

    def extract_activation(self, detail: dict | None) -> dict:
        """Best-effort activation metadata (activator address, activation tx).
        Field names must be confirmed live; TronGrid's AccountCreateContract
        history (normalize.py) is the primary, evidentiary source for
        activation -- this is a convenience cross-check only."""
        if not detail:
            return {}
        return {
            "activated_by": detail.get("activatedBy") or detail.get("activated_by"),
            "activation_tx": detail.get("activationTxHash") or detail.get("activation_tx"),
            "date_created": detail.get("date_created") or detail.get("dateCreated"),
        }
