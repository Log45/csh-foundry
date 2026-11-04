"""Database-wide transfer slots held by a dedicated autocommit connection, not a transaction.

PostgreSQL releases session advisory locks after a disconnected API process. No tenant row lock
or business transaction spans the request body or S3 transfer. Limits apply across API replicas.
"""

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.errors import ApplicationError


class TransferSlot:
    def __init__(
        self, sessions: sessionmaker[Session], tenant: UUID, global_limit: int, tenant_limit: int
    ):
        self.sessions, self.tenant = sessions, tenant
        self.global_limit, self.tenant_limit = global_limit, tenant_limit
        self.connection: Any = None
        self.locks: list[tuple[int, int]] = []

    def acquire(self) -> None:
        with self.sessions() as session:
            engine = session.get_bind()
        if not isinstance(engine, Engine):
            raise ApplicationError("upload_capacity", "Upload requires a dedicated connection", 503)
        self.connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            tenant_key = int.from_bytes(
                hashlib.sha256(self.tenant.bytes).digest()[:4], "big", signed=True
            )
            for namespace, limit in [
                (14214002, self.global_limit),
                (tenant_key, self.tenant_limit),
            ]:
                for slot in range(limit):
                    if self.connection.scalar(
                        text("SELECT pg_try_advisory_lock(:key, :slot)"),
                        {"key": namespace, "slot": slot},
                    ):
                        self.locks.append((namespace, slot))
                        break
                else:
                    raise ApplicationError(
                        "upload_capacity", "Upload capacity unavailable; retry", 503
                    )
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        if self.connection is not None:
            try:
                for key, slot in reversed(self.locks):
                    self.connection.execute(
                        text("SELECT pg_advisory_unlock(:key, :slot)"), {"key": key, "slot": slot}
                    )
            finally:
                self.locks.clear()
                self.connection.close()
                self.connection = None
