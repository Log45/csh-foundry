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
