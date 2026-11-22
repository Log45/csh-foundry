"""Exercise CI scope detection with actual Git histories and event payloads."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ci_changes.py"
spec = importlib.util.spec_from_file_location("ci_changes", SCRIPT)
assert spec and spec.loader
changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changes)


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "CI scope test")
    git("config", "user.email", "ci-scope@example.invalid")

    def commit(files):
        for name, content in files.items():
            path = tmp_path / name
            if content is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        git("add", "--all")
        git("commit", "-qm", "Test change")
        return git("rev-parse", "HEAD")

    base = commit({"README.md": "Initial docs", "app.py": "initial = True"})
    return tmp_path, git, commit, base


def event_for(name, base, head):
    if name == "pull_request":
        return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    if name == "merge_group":
        return {"merge_group": {"base_sha": base, "head_sha": head}}
    return {"before": base, "after": head}


@pytest.mark.parametrize("event", ["push", "pull_request", "merge_group"])
@pytest.mark.parametrize(
    "files, required",
    [
        ({"README.md": "Updated", "docs/setup.md": "Setup"}, False),
        ({"apps/studio/README.md": "Studio", "fixtures/VALIDATION.md": "Checks"}, False),
        (
            {"PLANS.md": "Plan", "AGENTS.md": "Instructions", "packages/sdk/CHANGELOG.md": "v1"},
            False,
        ),
        ({"docs/a\nstrange name.md": "Still documentation"}, False),
        ({"README.md": None}, False),
        ({"README.md": "Updated", "app.py": "changed = True"}, True),
        ({"app.py": None}, True),
        ({"uv.lock": "Dependency update"}, True),
        ({".github/workflows/ci.yaml": "Workflow update"}, True),
        ({"fixtures/manufacturing.ttl": "Fixture update"}, True),
        ({"docs/example.py": "Executable example"}, True),
        ({"docs/diagram.svg": "Asset"}, True),
        ({"apps/studio/help.mdx": "Executable documentation"}, True),
        ({"unknown-file": "Unclassified"}, True),
    ],
)
def test_scope_for_real_changes(repo, event, files, required):
    path, _, commit, base = repo
    head = commit(files)
    actual, _ = changes.regression_required(event, event_for(event, base, head), path)
    assert actual is required


def test_pr_checks_entire_branch_even_when_latest_push_is_docs_only(repo):
    path, _, commit, base = repo
    code = commit({"app.py": "changed = True"})
    head = commit({"README.md": "Follow-up docs"})
    assert changes.regression_required("push", event_for("push", code, head), path)[0] is False
    assert changes.regression_required("pull_request", event_for("pull_request", base, head), path)[
        0
    ]


def test_pr_ignores_unrelated_base_branch_changes(repo):
    path, git, commit, base = repo
    git("checkout", "-qb", "docs")
    head = commit({"README.md": "PR docs"})
    git("checkout", "-q", "main")
    advanced_base = commit({"app.py": "base_branch_update = True"})
    payload = event_for("pull_request", advanced_base, head)
    assert changes.regression_required("pull_request", payload, path)[0] is False
    # A merge queue uses its actual base-to-merged-head comparison instead.
    git("merge", "--no-edit", "docs")
    merged = git("rev-parse", "HEAD")
    assert changes.regression_required("merge_group", event_for("merge_group", base, merged), path)[
        0
    ]


@pytest.mark.parametrize("source,target", [("app.py", "docs/app.md"), ("README.md", "new.py")])
def test_rename_across_documentation_boundary_requires_ci(repo, source, target):
    path, git, _, base = repo
    (path / target).parent.mkdir(parents=True, exist_ok=True)
    git("mv", source, target)
    git("commit", "-qm", "Rename")
    head = git("rev-parse", "HEAD")
    assert changes.regression_required("push", event_for("push", base, head), path)[0]


@pytest.mark.parametrize("event", ["workflow_dispatch", "workflow_call", "schedule", "unknown"])
def test_manual_reusable_and_unknown_events_run_full_ci(repo, event):
    path, _, _, _ = repo
    assert changes.regression_required(event, {}, path)[0]


@pytest.mark.parametrize("base", ["0" * 40, "--output=README.md", "bad-sha"])
def test_invalid_or_new_ref_is_not_documentation_only(repo, base):
    path, _, _, head = repo
    assert changes.regression_required("push", event_for("push", base, head), path)[0]


def test_empty_diff_runs_full_ci(repo):
    path, _, _, base = repo
    assert changes.regression_required("push", event_for("push", base, base), path)[0]


def test_large_diff_does_not_hide_code_after_documentation_paths(repo):
    path, _, commit, base = repo
    files = {f"docs/page-{index}.md": "Documentation" for index in range(350)}
    files["z_app.py"] = "changed = True"
    head = commit(files)
    assert changes.regression_required("push", event_for("push", base, head), path)[0]


@pytest.mark.parametrize(
    "payload", ["not json", "null", "{}", json.dumps({"before": "1" * 40, "after": "2" * 40})]
)
def test_cli_falls_back_to_full_ci_for_missing_or_malformed_comparison(repo, payload):
    path, _, _, _ = repo
    event = path / "event.json"
    output = path / "output"
    event.write_text(payload)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=path,
        env=os.environ
        | {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == "run_ci=true\n"


def test_cli_publishes_documentation_skip_and_summary(repo):
    path, _, commit, base = repo
    head = commit({"README.md": "Updated"})
    event, output, summary = (path / name for name in ("event.json", "output", "summary"))
    event.write_text(json.dumps(event_for("push", base, head)))
    subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=path,
        env=os.environ
        | {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        check=True,
    )
    assert output.read_text() == "run_ci=false\n"
    assert "Documentation-only" in summary.read_text()


def test_workflow_gates_all_expensive_jobs_and_keeps_required_check():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())["jobs"]
    for name in ("storage", "static", "sdk", "studio", "backend", "integration"):
        needs = jobs[name]["needs"]
        assert "changes" in ([needs] if isinstance(needs, str) else needs)
        assert jobs[name]["if"] == "needs.changes.outputs.run_ci == 'true'"
    gate = jobs["regression"]
    assert gate["name"] == "CI / regression"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == set(jobs) - {"regression"}
    assert jobs["changes"]["steps"][0]["with"]["fetch-depth"] == 0
