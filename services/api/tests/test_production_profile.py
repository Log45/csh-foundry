"""Validate the deployable Compose contract, including previously rejected runtime mounts."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_production_profile_resolves_runtime_mounts_and_security_dependencies():
    env = os.environ | {
        "STUDIO_HOST": "studio.accept.test",
        "API_HOST": "api.accept.test",
        "IDENTITY_HOST": "identity.accept.test",
        "API_IMAGE": "api:acceptance",
        "INGRESS_IMAGE": "ingress:acceptance",
        "STUDIO_IMAGE": "studio:acceptance",
        "SEMANTIC_IMAGE": "semantic:acceptance",
        "SECRETS_DIRECTORY": "/disposable/secrets",
        "WAL_ARCHIVE_DIRECTORY": "/disposable/wal",
        "KEYCLOAK_IMPORT_DIRECTORY": "/disposable/realm",
        "TLS_DIRECTORY": "/disposable/tls",
        "WORKER_TENANT_ID": "00000000-0000-0000-0000-000000000001",
        "WORKER_SUBJECT_ID": "disposable",
        "WORKER_CATALOG_FILE": "/disposable/catalog.json",
        "INGESTION_DIRECTORY": "/disposable/input",
    }
    config = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                str(ROOT / "infrastructure/production/compose.yaml"),
                "--profile",
                "workers",
                "config",
                "--format",
                "json",
            ],
            env=env,
            text=True,
            timeout=15,
        )
    )
    services = config["services"]
    for name in ("api", "studio", "ingestion-worker", "semantic-worker"):
        service = services[name]
        assert service["read_only"]
        assert service["tmpfs"] == ["/tmp:size=128m,mode=1777"]
        assert "ALL" in service["cap_drop"]
        assert int(service["mem_limit"]) > 0 and float(service["cpus"]) > 0
        assert "ports" not in service
    assert services["api"]["depends_on"]["keycloak"]["condition"] == "service_healthy"
    assert services["keycloak"]["healthcheck"]["test"][0] == "CMD"
    broker_pool = services["keycloak"]["environment"]
    assert int(broker_pool["KC_DB_POOL_MIN_SIZE"]) == 2
    assert int(broker_pool["KC_DB_POOL_INITIAL_SIZE"]) == 2
    assert int(broker_pool["KC_DB_POOL_MAX_SIZE"]) == 10
    for name in ("api", "ingestion-worker"):
        assert any(
            v["target"] == "/run/secrets/FOUNDRY_INGESTION_CATALOG_JSON"
            for v in services[name]["volumes"]
        )
    assert {p["target"] for p in services["ingress"]["ports"]} == {80, 443}
    privileged = {"postgres_password", "keycloak_password", "keycloak_admin_password"}
    for name in ("api", "studio", "ingestion-worker", "semantic-worker"):
        assert not privileged.intersection(s["source"] for s in services[name]["secrets"])


def test_semantic_worker_import_does_not_initialize_tabular_runtime():
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import ontology_platform.semantic.worker; "
            "assert 'polars' not in sys.modules; "
            "assert 'ontology_platform.ingestion.worker' not in sys.modules",
        ],
        check=True,
        cwd=ROOT,
    )
