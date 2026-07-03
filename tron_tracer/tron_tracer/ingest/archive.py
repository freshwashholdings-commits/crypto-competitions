from __future__ import annotations

from sqlalchemy.orm import Session

from tron_tracer.db.models import RawApiResponse
from tron_tracer.ingest.http_client import ArchiveFn, sha256_hex


def make_db_archive_fn(session: Session) -> ArchiveFn:
    """Bind an ArchiveFn that persists every raw response to `raw_api_responses`
    immediately (autoflush) so the row id can be threaded through to the
    normalized rows that get derived from it."""

    def archive(source: str, endpoint: str, params: dict, http_status: int, body: str) -> int:
        row = RawApiResponse(
            source=source,
            endpoint=endpoint,
            params=params,
            http_status=http_status,
            body=body,
            sha256=sha256_hex(body),
        )
        session.add(row)
        session.flush()  # assign row.id without committing the whole transaction
        return row.id

    return archive
