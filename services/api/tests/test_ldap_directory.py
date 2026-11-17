"""Loopback LDAP protocol fixture with verified StartTLS and affine paging."""

import socketserver
import ssl
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from ldap3.operation.search import compile_filter, parse_filter
from ldap3.protocol.rfc2696 import RealSearchControlValue, paged_search_control
from ldap3.protocol.rfc4511 import LDAPMessage, ProtocolOp, SearchRequest
from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.security.ldap_directory import PAGE_CONTROL, PAGE_SIZE, LdapDirectory
from pyasn1.codec.ber.decoder import decode
from pyasn1.codec.ber.encoder import encode
from pyasn1.type.namedtype import NamedType, NamedTypes
from pyasn1.type.univ import Any
from test_phase22 import profile

BASE = "ou=people,dc=example,dc=test"


def make_certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "trusted.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path = tmp_path / "fixture-key.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


def fixture_spec(parent, name, child):
    # ldap3's recursive encoding schema cannot decode nested filter sets. Keep the
    # serialized filter so the fixture can compare it to the prescribed RFC 4515 expression.
    return NamedTypes(
        *(
            NamedType(name, child) if field.name == name else field
            for field in parent.componentType.namedTypes
        )
    )


class WireSearch(SearchRequest):
    componentType = fixture_spec(SearchRequest, "filter", Any())


class WireOperation(ProtocolOp):
    componentType = fixture_spec(ProtocolOp, "searchRequest", WireSearch())


class WireMessage(LDAPMessage):
    componentType = fixture_spec(LDAPMessage, "protocolOp", WireOperation())


def filter_bytes(expression):
    return encode(
        compile_filter(parse_filter(expression, None, True, True, None, False).elements[0])
    )


def receive(sock):
    def take(n):
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    header = take(2)
    length = header[1]
    if length & 0x80:
        more = take(length & 0x7F)
        header += more
        length = int.from_bytes(more, "big")
    return decode(header + take(length), asn1Spec=WireMessage())[0]


@pytest.fixture
def ldap_fixture(tmp_path):
    from threading import Thread

    context, ca = make_certificate(tmp_path)
    received = []
    behavior = {"oversized": False}

    def reply(key, operation, *, attributes=None, cookie=None):
        message = LDAPMessage()
        message["messageID"] = key
        data = message["protocolOp"][operation]
        if attributes is None:
            data["resultCode"], data["matchedDN"], data["diagnosticMessage"] = 0, "", ""
        else:
            data["object"] = "uid=private-dn," + BASE
            for name, value in attributes.items():
                entry = data["attributes"].componentType.clone()
                entry["type"] = name
                entry["vals"].append(value)
                data["attributes"].append(entry)
        if cookie is not None:
            message["controls"].append(paged_search_control(size=60, cookie=cookie))
        return encode(message)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                first = receive(self.request)
                assert first["protocolOp"].getName() == "extendedReq"
                assert (
                    str(first["protocolOp"]["extendedReq"]["requestName"])
                    == "1.3.6.1.4.1.1466.20037"
                )
                self.request.sendall(reply(first["messageID"], "extendedResp"))
                with context.wrap_socket(self.request, server_side=True) as secure:
                    bind = receive(secure)
                    assert bind["protocolOp"].getName() == "bindRequest"
                    assert str(bind["protocolOp"]["bindRequest"]["name"]) == ""
                    secure.sendall(reply(bind["messageID"], "bindResponse"))
                    page = 0
                    while True:
                        msg = receive(secure)
                        op = msg["protocolOp"]
                        if op.getName() == "unbindRequest":
                            return
                        request = op["searchRequest"]
                        control = msg["controls"][0]
                        assert str(control["controlType"]) == PAGE_CONTROL
                        assert bool(control["criticality"])
                        paging, _ = decode(
                            control["controlValue"].asOctets(), asn1Spec=RealSearchControlValue()
                        )
                        assert int(paging["size"]) == PAGE_SIZE
                        assert paging["cookie"].asOctets() == (b"same-cookie" if page else b"")
                        assert str(request["baseObject"]) == BASE
                        assert int(request["scope"]) == 1
                        assert int(request["derefAliases"]) == 0
                        assert list(map(str, request["attributes"])) == ["uid", "displayName", "cn"]
                        received.append((page, request["filter"].asOctets()))
                        payload = b"".join(
                            reply(
                                msg["messageID"],
                                "searchResEntry",
                                attributes={
                                    "uid": f"alice{page}",
                                    "displayName": f"alice{page}",
                                    "cn": f"Alice Example {page}",
                                },
                            )
                            for _ in range(PAGE_SIZE + 1 if behavior["oversized"] else 1)
                        )
                        secure.sendall(
                            payload
                            + reply(
                                msg["messageID"],
                                "searchResDone",
                                cookie=b"same-cookie" if page < 2 else b"",
                            )
                        )
                        page += 1
            except (ssl.SSLError, EOFError, ConnectionError):
                return

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], ca, received, behavior
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def directory(ldap_fixture):
    port, ca, _, _ = ldap_fixture
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused/unused",
        auth_mode="oidc",
        oidc_providers=(profile(),),
        directory_sources=("ldap",),
        directory_ldap_url=f"ldap://localhost:{port}",
        directory_ldap_base_dn=BASE,
        directory_ldap_ca_bundle=ca,
    )
    ldap = LdapDirectory(settings)
    try:
        yield ldap
    finally:
        ldap.close()


def test_verified_paging_browse_filter_and_private_cursor(ldap_fixture, directory):
    _, _, requests, _ = ldap_fixture
    scope = ("sender", uuid4(), "issuer", "subject")
    people, first = directory.page(scope, "", None)
    assert [(p.username, p.display_name) for p in people] == [("alice0", "Alice Example 0")]
    with pytest.raises(ApplicationError, match="Restart"):
        directory.page(("other", *scope[1:]), "", first)
    with pytest.raises(ApplicationError, match="Restart"):
        directory.page(scope, "changed", first)
    people, second = directory.page(scope, "", first)
    assert second != first
    assert people[0].username == "alice1"
    with pytest.raises(ApplicationError, match="Restart"):
        directory.page(scope, "", first)
    people, cursor = directory.page(scope, "", second)
    assert people[0].username == "alice2"
    assert cursor is None and not directory.pending
    assert [page for page, _ in requests] == [0, 1, 2]
    assert all(expression == filter_bytes("(uid=*)") for _, expression in requests)

    directory.settings.directory_ldap_member_filter = "(memberOf=approved)"
    _, cursor = directory.page(scope, "al*(\\)\x00", None)
    expected = (
        r"(&(uid=*)(|(uid=al\2a\28\5c\29\00*)"
        r"(displayName=al\2a\28\5c\29\00*)(cn=al\2a\28\5c\29\00*))(memberOf=approved))"
    )
    assert requests[-1][1] == filter_bytes(expected)
    directory.cancel(cursor, scope)
    assert not directory.pending


def test_tls_and_oversized_pages_fail_closed(ldap_fixture, directory):
    port, ca, requests, behavior = ldap_fixture
    scope = ("sender", uuid4(), "issuer", "subject")
    directory.settings.directory_ldap_url = f"ldap://127.0.0.1:{port}"
    with pytest.raises(ApplicationError, match="LDAP recipient directory is unavailable"):
        directory.page(scope, "", None)
    directory.settings.directory_ldap_url = f"ldap://localhost:{port}"
    directory.settings.directory_ldap_ca_bundle = None
    with pytest.raises(ApplicationError, match="LDAP recipient directory is unavailable"):
        directory.page(scope, "", None)
    assert not requests
    directory.settings.directory_ldap_ca_bundle = ca
    behavior["oversized"] = True
    with pytest.raises(ApplicationError, match="LDAP recipient directory is unavailable"):
        directory.page(scope, "", None)
    assert not directory.pending
