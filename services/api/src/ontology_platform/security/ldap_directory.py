"""Anonymous, verified StartTLS lookup with connection-affine RFC 2696 pages."""

import ssl
from contextlib import suppress
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock, Timer
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from ldap3 import (  # type: ignore[import-untyped]
    ANONYMOUS,
    DEREF_NEVER,
    LEVEL,
    NONE,
    Connection,
    Server,
    Tls,
)
from ldap3.core.exceptions import LDAPException  # type: ignore[import-untyped]
from ldap3.utils.conv import escape_filter_chars  # type: ignore[import-untyped]
from pyasn1.error import PyAsn1Error  # type: ignore[import-untyped]

from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError

PAGE_SIZE = 20
PAGE_TTL_SECONDS = 45
PAGE_CONTROL = "1.2.840.113556.1.4.319"
Scope = tuple[str, UUID, str | None, str | None]


def valid_username(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and all(char.isprintable() and not char.isspace() for char in value)
    )


def search_filter(query: str, member_filter: str | None) -> str:
    conditions = "(uid=*)"
    if query:
        prefix = escape_filter_chars(query) + "*"
        conditions += f"(|(uid={prefix})(displayName={prefix})(cn={prefix}))"
    if member_filter:
        conditions += member_filter
    return f"(&{conditions})" if query or member_filter else conditions


def first_value(attributes: dict[str, Any], name: str) -> str:
    for value in attributes.get(name.lower(), []):
        if isinstance(value, str) and value.strip() and value.isprintable():
            return value
    return ""


@dataclass(frozen=True)
class Person:
    username: str
    display_name: str


@dataclass
class Search:
    connection: Connection
    scope: Scope
    query: str
    cookie: bytes = b""


class LdapDirectory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.connections = BoundedSemaphore(32)
        self.lock = Lock()
        self.pending: dict[UUID, tuple[Search, Timer]] = {}

    def connect(self) -> Connection:
        endpoint = urlsplit(self.settings.directory_ldap_url or "")
        host = endpoint.hostname
        ca = self.settings.directory_ldap_ca_bundle
        server = Server(
            host,
            port=endpoint.port or 389,
            connect_timeout=3,
            get_info=NONE,
            tls=Tls(validate=ssl.CERT_REQUIRED, sni=host, ca_certs_file=str(ca) if ca else None),
        )
        connection = Connection(
            server,
            authentication=ANONYMOUS,
            auto_referrals=False,
            raise_exceptions=True,
            receive_timeout=3,
            check_names=False,
        )
        try:
            connection.open()
            if not connection.start_tls() or not connection.bind():
                raise ValueError("StartTLS or anonymous bind failed")
        except BaseException:
            self.disconnect(connection)
            raise
        return connection

    @staticmethod
    def disconnect(connection: Connection) -> None:
        try:
            connection.unbind()
        except (LDAPException, OSError):
            with suppress(LDAPException, OSError):
                connection.strategy.close()

    def release(self, search: Search) -> None:
        try:
            self.disconnect(search.connection)
        finally:
            self.connections.release()

    def take(self, key: UUID, scope: Scope, query: str | None = None) -> Search | None:
        with self.lock:
            entry = self.pending.get(key)
            if entry is None:
                return None
            search, timer = entry
            if search.scope != scope or (query is not None and search.query != query):
                return None
            del self.pending[key]
            timer.cancel()
            return search

    def cancel(self, key: UUID, scope: Scope) -> None:
        search = self.take(key, scope)
        if search is not None:
            self.release(search)

    def close(self) -> None:
        with self.lock:
            entries = list(self.pending.values())
            self.pending.clear()
        for search, timer in entries:
            timer.cancel()
            self.release(search)

    def page(
        self, scope: Scope, query: str, cursor: UUID | None
    ) -> tuple[list[Person], UUID | None]:
        search = None
        retained = False
        try:
            if cursor is not None:
                search = self.take(cursor, scope, query)
                if search is None:
                    raise ApplicationError(
                        "directory_restart", "Directory page expired. Restart the search.", 409
                    )
            else:
                if not self.connections.acquire(blocking=False):
                    raise ApplicationError("directory_busy", "Directory is busy. Try again.", 503)
                try:
                    search = Search(self.connect(), scope, query)
                except BaseException:
                    self.connections.release()
                    raise

            connection = search.connection
            connection.search(
                self.settings.directory_ldap_base_dn,
                search_filter(query, self.settings.directory_ldap_member_filter),
                search_scope=LEVEL,
                dereference_aliases=DEREF_NEVER,
                attributes=["uid", "displayName", "cn"],
                time_limit=3,
                paged_size=PAGE_SIZE,
                paged_criticality=True,
                paged_cookie=search.cookie,
            )
            controls = connection.result.get("controls", {})
            cookie = controls.get(PAGE_CONTROL, {}).get("value", {}).get("cookie")
            entries = connection.response
            if (
                connection.result.get("result") != 0
                or not isinstance(entries, list)
                or len(entries) > PAGE_SIZE
                or not isinstance(cookie, bytes)
                or len(cookie) > 4096
            ):
                raise ValueError("Invalid LDAP page")
            people = []
            for entry in entries:
                if entry.get("type") != "searchResEntry":
                    continue
                attributes = {key.lower(): value for key, value in entry["attributes"].items()}
                uid = first_value(attributes, "uid")
                if not valid_username(uid):
                    continue
                display = first_value(attributes, "displayName").strip()
                cn = first_value(attributes, "cn").strip()
                if not display or display.casefold() == uid.casefold():
                    display = cn or uid
                people.append(Person(uid, display[:200]))

            if not cookie:
                return people, None
            search.cookie = cookie
            key = uuid4()
            timer = Timer(PAGE_TTL_SECONDS, self.cancel, args=(key, scope))
            timer.daemon = True
            with self.lock:
                self.pending[key] = (search, timer)
                timer.start()
            retained = True
            return people, key
        except (LDAPException, OSError, ValueError, PyAsn1Error, IndexError, KeyError, TypeError):
            if cursor is not None:
                raise ApplicationError(
                    "directory_restart", "Directory page unavailable. Restart the search.", 409
                ) from None
            raise ApplicationError(
                "directory_unavailable", "LDAP recipient directory is unavailable", 503
            ) from None
        finally:
            if search is not None and not retained:
                self.release(search)
