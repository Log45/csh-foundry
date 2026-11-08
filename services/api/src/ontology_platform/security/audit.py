"""Append audit records without populating absent optional correlation fields."""

from collections.abc import Sequence

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ontology_platform.db.models import AuthorizationAudit


def persist_audit(session: Session, rows: Sequence[AuthorizationAudit]) -> None:
    # ORM bulk INSERT omits unset/None optional fields. Besides preserving DB defaults this
    # lets historical migration fixtures append ordinary audit records before correlation
    # columns exist; actual job audit always supplies and persists its complete context.
    if rows:
        session.execute(
            insert(AuthorizationAudit),
            [
                {
                    column.name: value
                    for column in AuthorizationAudit.__table__.columns
                    if (value := getattr(row, column.name, None)) is not None
                }
                for row in rows
            ],
        )
