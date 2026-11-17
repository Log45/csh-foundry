"""Picker contracts and short-lived, actor-bound LDAP selections."""

import time
from uuid import UUID

from pydantic import BaseModel

from ontology_platform.config import DirectorySource
from ontology_platform.errors import ApplicationError
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.ldap_directory import Scope, valid_username


class DirectoryRecipient(BaseModel):
    source: DirectorySource
    id: str
    username: str
    display_name: str


class RecipientPage(BaseModel):
    results: list[DirectoryRecipient]
    next_cursor: UUID | None = None
    unavailable_sources: list[DirectorySource]


def directory_scope(p: Principal) -> Scope:
    return (p.principal_id, p.tenant_id, p.identity_provider, p.external_subject)


def selection_id(codec: CursorCodec, p: Principal, username: str) -> str:
    scope = p.principal_id, str(p.tenant_id), p.identity_provider, p.external_subject
    return codec.encode(
        {
            "kind": "ldap-recipient",
            "actor": codec.bind(scope, purpose="ldap-selection"),
            "username": username,
        }
    )


def selected_username(codec: CursorCodec, p: Principal, selection: str) -> str:
    error = ApplicationError("directory_selection_expired", "Select the recipient again.", 409)
    try:
        payload = codec.decode(selection)
    except ApplicationError:
        raise error from None
    username = payload.get("username")
    scope = p.principal_id, str(p.tenant_id), p.identity_provider, p.external_subject
    if (
        payload.get("kind") != "ldap-recipient"
        or payload.get("actor") != codec.bind(scope, purpose="ldap-selection")
        or time.time() - payload["issued"] > 600
        or not isinstance(username, str)
        or not valid_username(username)
    ):
        raise error
    return username
