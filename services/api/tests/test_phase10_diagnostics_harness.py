"""Diagnostic evidence retains failures and correlation without retaining private fields."""

import importlib
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("phase10_span_capture"), importlib.import_module(
        "phase10_diagnostics"
    )


def test_span_capture_allowlist_and_bound(monkeypatch):
    module, _ = modules(monkeypatch)
    capture = module.SpanCapture.__new__(module.SpanCapture)
    capture.output, capture.lock, capture.count = io.StringIO(), threading.Lock(), 19999
    record = json.dumps({"event": "request_span", "trace_id": "a" * 32, "token": "private"})
    capture.consume(SimpleNamespace(stdout=iter([record, record])))
    rows = capture.output.getvalue().splitlines()
    assert len(rows) == 1 and "private" not in rows[0] and capture.count == 20000


def test_correlate_preserves_slow_failed_samples_and_ingress_parent(monkeypatch, tmp_path):
    _, module = modules(monkeypatch)
    trace = "a" * 32
    (tmp_path / "failed.json").write_text(
        json.dumps(
            {
                "measurements": [
                    {
                        "concurrency": 8,
                        "samples": [
                            {
                                "operation": "query",
                                "trace_id": trace,
                                "seconds": 0.75,
                                "result": "FAIL",
                            }
                        ],
                    }
                ]
            }
        )
    )
    (tmp_path / "request-spans.jsonl").write_text(
        json.dumps(
            {
                "event": "ingress_status",
                "trace_id": "00-" + trace + "-" + "b" * 16 + "-01",
                "duration": 0.7,
            }
        )
        + "\n"
    )
    module.correlate(SimpleNamespace(output=tmp_path, dc=lambda *args: ""))
    result = json.loads((tmp_path / "correlated-requests.json").read_text())
    assert result["slow_requests"] == 1
    assert result["requests"][0]["result"] == "FAIL"
    assert result["requests"][0]["spans"][0]["duration"] == 0.7


@pytest.mark.parametrize("enabled", [False, True])
def test_curl_diagnostic_transport_preserves_status_and_redacts(monkeypatch, tmp_path, enabled):
    modules(monkeypatch)
    acceptance = importlib.import_module("accept_phase10").Acceptance.__new__(
        importlib.import_module("accept_phase10").Acceptance
    )
    acceptance.root, acceptance.ingress_port = tmp_path, "12345"
    acceptance.diagnostic_requests, acceptance.request_local = enabled, threading.local()

    def run(args, **kwargs):
        Path(args[args.index("-D") + 1]).write_text(
            "HTTP/1.1 200 OK\nContent-Type: application/json\n"
        )
        Path(args[args.index("-o") + 1]).write_text('{"ok":true}')
        return (
            json.dumps(
                {
                    "http_code": 200,
                    **dict.fromkeys(
                        [
                            "time_namelookup",
                            "time_connect",
                            "time_appconnect",
                            "time_pretransfer",
                            "time_starttransfer",
                            "time_total",
                        ],
                        0.01,
                    ),
                    "url_effective": "private",
                }
            )
            if enabled
            else "200"
        )

    acceptance.run = run
    response = acceptance.request("studio.accept.test", "/bff", headers={"Authorization": "secret"})
    assert response.status_code == 200 and response.json() == {"ok": True}
    if enabled:
        timing = acceptance.request_local.timing
        assert len(timing["trace_id"]) == 32
        assert "secret" not in str(timing) and "private" not in str(timing)
    assert not list(tmp_path.glob("*.body")) and not list(tmp_path.glob("*.headers"))
