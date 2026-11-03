"""The destructive recovery drill must refuse developer containers and unrelated mounts."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("phase10_pitr", ROOT / "scripts/phase10_pitr.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_recovery_refuses_developer_container_and_non_disposable_project(tmp_path):
    archive = tmp_path / "foundry-accept-1234abcd" / "wal"
    info = {"Config": {"Labels": {"com.docker.compose.project": "csh-foundry"}}, "Mounts": []}
    with pytest.raises(ValueError, match="disposable acceptance"):
        module.validate_source(info, "csh-foundry", archive)
    with pytest.raises(ValueError, match="does not belong"):
        module.validate_source(info, "foundry-accept-1234abcd", archive)


def test_recovery_refuses_an_unrelated_wal_mount(tmp_path):
    project = "foundry-accept-1234abcd"
    archive = tmp_path / project / "wal"
    info = {
        "Config": {"Labels": {"com.docker.compose.project": project}},
        "Mounts": [{"Source": str(tmp_path / "developer-wal"), "Destination": "/archive"}],
    }
    with pytest.raises(ValueError, match="differs"):
        module.validate_source(info, project, archive)
    with pytest.raises(ValueError, match="own WAL"):
        module.validate_source(info, project, tmp_path / "developer-wal")


def test_recovery_accepts_only_the_exact_desktop_bind_translation(tmp_path):
    project = "foundry-accept-1234abcd"
    archive = tmp_path / project / "wal"
    info = {
        "Config": {"Labels": {"com.docker.compose.project": project}},
        "Mounts": [
            {"Type": "bind", "Source": "/host_mnt" + str(archive), "Destination": "/archive"}
        ],
    }
    module.validate_source(info, project, archive)
    info["Mounts"][0]["Source"] += "/another-directory"
    with pytest.raises(ValueError, match="differs"):
        module.validate_source(info, project, archive)


@pytest.mark.parametrize("change", [None, "external", "different-name", "different-owner"])
def test_application_recovery_requires_owned_internal_network(change):
    project = "foundry-accept-1234abcd"
    info = {
        "Name": project + "_data",
        "Internal": True,
        "Labels": {"com.docker.compose.project": project},
    }
    if change == "external":
        info["Internal"] = False
    elif change == "different-name":
        info["Name"] = "csh-foundry_data"
    elif change == "different-owner":
        info["Labels"]["com.docker.compose.project"] = "csh-foundry"
    if change is None:
        module.validate_recovery_network(info, project)
    else:
        with pytest.raises(ValueError, match="network"):
            module.validate_recovery_network(info, project)


def test_restore_cleanup_rejects_non_disposable_directory(tmp_path):
    with pytest.raises(ValueError, match="Only disposable"):
        module.cleanup_restore(None, None, tmp_path / "developer")


def test_restore_cleanup_rejects_source_database_volume(tmp_path):
    project = "foundry-accept-1234abcd"
    with pytest.raises(ValueError, match="volume does not belong"):
        module.cleanup_restore(None, project + "_database", tmp_path / project)


def test_restore_cleanup_cannot_stop_a_developer_container(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []

    def inspect_only(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='[{"Name":"/csh-foundry-postgres-1"}]')

    monkeypatch.setattr(module.subprocess, "run", inspect_only)
    with pytest.raises(ValueError, match="non-restore container"):
        module.cleanup_restore("developer-container", None, tmp_path / "foundry-accept-1234abcd")
    assert calls == [["docker", "inspect", "developer-container"]]

    def unavailable(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr="Cannot connect to Docker daemon")

    monkeypatch.setattr(module.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="not proof"):
        module.cleanup_restore("developer-container", None, tmp_path / "foundry-accept-1234abcd")
    assert calls == [["docker", "inspect", "developer-container"]] * 2
