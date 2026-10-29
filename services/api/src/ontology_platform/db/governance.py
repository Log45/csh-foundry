"""Shared public unit-of-work boundary for governed module services."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.models import Ontology, Tenant
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Authorizer, Principal
from ontology_platform.security.query import TransactionAuthorizer

SCHEMA_REVISION = "0013_security"


def missing(resource: str) -> ApplicationError:
    return ApplicationError("not_found", f"{resource} not found in this tenant", 404)


class GovernedService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        *,
        session: Session | None = None,
    ):
        self.sessions = sessions
        self.authorizer = authorizer
        self.transaction_session = session

    @contextmanager
    def operation(
        self, principal: Principal, operation: str, resource: str, *, provision: bool = False
    ) -> Iterator[Session]:
        if not isinstance(principal, Principal):
            raise ApplicationError("authentication_required", "Principal required", 401)
        try:
            with (
                nullcontext(self.transaction_session)
                if self.transaction_session is not None
                else self.sessions.begin()
            ) as session:
                with (
                    self.authorizer.security_context(session, principal)
                    if isinstance(self.authorizer, TransactionAuthorizer)
                    else nullcontext()
                ):
                    self.authorizer.require(
                        principal, operation, f"{principal.tenant_id}/{resource}"
                    )
                    if not provision and session.get(Tenant, principal.tenant_id) is None:
                        raise ApplicationError(
                            "tenant_unavailable", "Tenant must be provisioned", 403
                        )
                    yield session
        except IntegrityError as exc:
            raise ApplicationError(
                "constraint_conflict", "Persistence constraint conflict", 409
            ) from exc

    @staticmethod
    def ontology(
        session: Session, principal: Principal, ontology_id: str, *, write: bool = False
    ) -> Ontology:
        if (
            principal.authentication_method == "delegated"
            and ontology_id != principal.delegation_ontology
        ):
            raise ApplicationError("forbidden", "Delegation does not cover this ontology", 403)
        # Coarse per-ontology locking serializes writes/cardinality/uniqueness and activation.
        # Readers take SHARE to observe schema and data from the same activation interval.
        row = session.scalar(
            select(Ontology)
            .where(Ontology.tenant_id == principal.tenant_id, Ontology.id == ontology_id)
            .with_for_update(read=not write)
        )
        if row is None:
            raise missing("Ontology")
        return row
