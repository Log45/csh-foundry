"""The required CI gate must reject tests that never ran, even with a zero exit code."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "check_test_report", ROOT / "scripts/check_test_report.py"
)
assert spec and spec.loader
report_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_module)


@pytest.mark.parametrize(
    "body",
    [
        "<testsuites />",
        '<testsuite tests="1" skipped="0" />',
        '<testsuite><testcase name="storage">'
        '<skipped message="MinIO missing" /></testcase></testsuite>',
        '<testsuite><testcase name="query"><failure /></testcase></testsuite>',
        '<testsuite><testcase name="setup"><error /></testcase></testsuite>',
        '<testsuites><testsuite><testcase name="ok" /></testsuite>'
        '<testsuite><testcase name="skipped"><skipped /></testcase></testsuite></testsuites>',
    ],
)
def test_rejects_incomplete_or_failed_execution(tmp_path, body):
    report = tmp_path / "results.xml"
    report.write_text(body)
    with pytest.raises(ValueError):
        report_module.check_report(report)


@pytest.mark.parametrize("wrapper", ["testsuite", "testsuites"])
def test_accepts_executed_tests(tmp_path, wrapper):
    report = tmp_path / "results.xml"
    report.write_text(f'<{wrapper}><testcase name="postgres" /><testcase name="s3" /></{wrapper}>')
    assert report_module.check_report(report) == 2


def test_missing_report_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        report_module.check_report(tmp_path / "missing.xml")


@pytest.mark.parametrize("result_type", ["pytest.xfail", "pytest.skip"])
def test_only_documented_strict_xfail_is_allowed(tmp_path, result_type, capsys):
    report = tmp_path / "results.xml"
    classname, name, reason = report_module.KNOWN_XFAIL
    report.write_text(
        f'<testsuite><testcase name="ok" /><testcase classname="{classname}" name="{name}">'
        f'<skipped type="{result_type}" message="{reason}" /></testcase></testsuite>'
    )
    if result_type == "pytest.xfail":
        assert report_module.check_report(report) == 1
        assert "EXPECTED FAILURE (not PASS)" in capsys.readouterr().out
    else:
        with pytest.raises(ValueError):
            report_module.check_report(report)


def test_shards_cover_collection_once_and_honor_marker_exclusions(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = scale: large acceptance\n")
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        + "\n".join(f"def test_feature_{index}(): pass" for index in range(12))
        + "\n@pytest.mark.scale\ndef test_large(): pass\n"
    )
    selections = []
    for index in range(4):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "scripts.ci_shard",
                "--ci-shard",
                f"{index}/4",
                "--collect-only",
                "-q",
                "-m",
                "not scale",
                "-c",
                str(tmp_path / "pytest.ini"),
                str(tmp_path / "test_sample.py"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        selections.append({line for line in result.stdout.splitlines() if "::test_" in line})
    assert all(len(selection) == 3 for selection in selections)
    assert len(set.union(*selections)) == 12
    assert sum(map(len, selections)) == 12
    assert all("test_large" not in case for selection in selections for case in selection)


@pytest.mark.parametrize("value", ["bad", "0/0", "4/4", "-1/4"])
def test_invalid_shard_is_a_usage_error(value):
    spec = importlib.util.spec_from_file_location("ci_shard", ROOT / "scripts/ci_shard.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(pytest.UsageError):
        module.shard(value)


@pytest.mark.parametrize("status", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("dependency", ["static", "sdk", "studio", "backend", "integration"])
def test_actual_required_gate_rejects_unsuccessful_dependencies(status, dependency):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    gate = workflow["jobs"]["regression"]
    results = {name: {"result": "success"} for name in gate["needs"]}
    results[dependency] = {"result": status}
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", gate["steps"][0]["run"]],
        cwd=ROOT,
        env=os.environ | {"RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (status == "success")
