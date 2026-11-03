"""Rendered deployment boundaries and negative security contracts (not cluster admission)."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml
from ontology_platform.config import Settings
from pydantic import SecretStr, ValidationError
from test_phase1 import database, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("kube", ROOT / "scripts/validate_kubernetes.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def render(profile):
    return list(
        yaml.safe_load_all(
            subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / "infrastructure/kubernetes" / profile)],
                text=True,
            )
        )
    )


@pytest.mark.parametrize("profile", ["base", "overlays/okd", "overlays/self-hosted", "migration"])
def test_rendered_profiles(profile):
    resources = render(profile)
    module.validate(resources)
    assert not any(r["kind"] == "StatefulSet" for r in resources)
    with pytest.raises(AssertionError):
        module.validate(resources, production=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "uid",
        "escalation",
        "capability",
        "host",
        "port",
        "rootfs",
        "selector",
        "secret_mount",
        "privileged",
        "scc",
    ],
)
def test_reject_unsafe_workload(mutation):
    resources = render("overlays/okd")
    deploy = next(
        r for r in resources if r["kind"] == "Deployment" and r["metadata"]["name"] == "api"
    )
    pod = deploy["spec"]["template"]["spec"]
    c = pod["containers"][0]
    match mutation:
        case "uid":
            c["securityContext"]["runAsUser"] = 0
        case "escalation":
            c["securityContext"]["allowPrivilegeEscalation"] = True
        case "capability":
            c["securityContext"]["capabilities"]["add"] = ["NET_ADMIN"]
        case "host":
            pod["hostNetwork"] = True
        case "port":
            c["ports"][0]["containerPort"] = 80
        case "rootfs":
            c["securityContext"]["readOnlyRootFilesystem"] = False
        case "selector":
            deploy["spec"]["selector"]["matchLabels"]["wrong"] = "selector"
        case "secret_mount":
            c["volumeMounts"][0]["name"] = "missing"
        case "privileged":
            c["securityContext"]["privileged"] = True
        case "scc":
            deploy["metadata"]["annotations"] = {"openshift.io/required-scc": "anyuid"}
    with pytest.raises(AssertionError):
        module.validate(resources)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?sslmode=require",
        "?sslmode=verify-full",
        "?sslmode=verify-full&sslmode=disable&sslrootcert=/ca.pem",
    ],
)
def test_external_database_requires_verified_tls(query):
    with pytest.raises(ValidationError, match="verify-full"):
        Settings(
            database_url=SecretStr("postgresql+psycopg://u:p@db/foundry" + query),
            database_tls_required=True,
            _env_file=None,
        )


def test_external_database_accepts_explicit_ca():
    Settings(
        database_url=SecretStr(
            "postgresql+psycopg://u:p@db/foundry?sslmode=verify-full"
            "&sslrootcert=/run/trust/postgres-ca.pem"
        ),
        database_tls_required=True,
        _env_file=None,
    )


def test_migration_refuses_concurrent_session_and_checks_current_schema(world, monkeypatch):  # noqa: F811
    from sqlalchemy import text

    spec = importlib.util.spec_from_file_location(
        "migration", ROOT / "scripts/migrate_kubernetes.py"
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration, "get_settings", lambda: world.settings)
    monkeypatch.setattr(migration, "create_engine", lambda *args, **kwargs: world.engine)
    with world.engine.connect() as locked:
        locked.execute(text("SELECT pg_advisory_lock(7041000017)"))
        locked.commit()
        try:
            with pytest.raises(RuntimeError, match="Another migration"):
                migration.main()
        finally:
            locked.execute(text("SELECT pg_advisory_unlock(7041000017)"))
            locked.commit()
    migration.main()


@pytest.mark.parametrize("failure", ["migration", "active-job", "none"])
def test_rollout_never_applies_deployments_before_migration_success(tmp_path, monkeypatch, failure):
    import json
    import sys
    import types

    # The target receives no commands: subprocess is a recording transport.
    fake_validator = types.ModuleType("validate_kubernetes")
    fake_validator.validate = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "validate_kubernetes", fake_validator)
    spec = importlib.util.spec_from_file_location("rollout", ROOT / "scripts/rollout_kubernetes.py")
    assert spec and spec.loader
    rollout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rollout)
    configuration = tmp_path / "application.yaml"
    configuration.write_text("apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: api}\n")
    migration = tmp_path / "migration.yaml"
    migration.write_text("apiVersion: batch/v1\nkind: Job\nmetadata: {name: foundry-migrate}\n")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if failure == "migration" and "job/foundry-migrate" in command:
            raise subprocess.CalledProcessError(1, command)

    def read(command, **kwargs):
        if "job" in command:
            return json.dumps({"status": {"active": 1}}) if failure == "active-job" else ""
        return json.dumps({"items": [{"metadata": {"name": "api"}}]})

    monkeypatch.setattr(rollout.subprocess, "run", run)
    monkeypatch.setattr(rollout.subprocess, "check_output", read)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rollout",
            "--context",
            "disposable",
            "--namespace",
            "test",
            "--configuration",
            str(configuration),
            "--migration",
            str(migration),
            "--apply",
        ],
    )
    if failure != "none":
        with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
            rollout.main()
        assert not any(str(configuration) in c for c in calls)
    else:
        rollout.main()
        migration_wait = next(i for i, c in enumerate(calls) if "job/foundry-migrate" in c)
        apply = next(i for i, c in enumerate(calls) if str(configuration) in c)
        assert migration_wait < apply
