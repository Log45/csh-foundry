"""Skip expensive regression only for a confirmed documentation-only Git comparison."""

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


def documentation_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        path.name in {"README.md", "CHANGELOG.md", "AGENTS.md"}
        or name in {"PLANS.md", "fixtures/VALIDATION.md"}
        or (name.startswith("docs/") and path.suffix == ".md")
    )


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=60,
    ).stdout


def regression_required(event_name: str, event: dict[str, Any], repo: Path) -> tuple[bool, str]:
    if event_name == "push":
        base, head = event["before"], event["after"]
    elif event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
    elif event_name == "merge_group":
        base, head = event["merge_group"]["base_sha"], event["merge_group"]["head_sha"]
    else:
        return True, "Manual, reusable or unknown event: full regression required."

    # Never interpret event-provided refs as Git options or guess a new branch's baseline.
    for revision in (base, head):
        if not isinstance(revision, str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", revision
        ):
            return True, "Invalid comparison revision: full regression required."
        if set(revision) == {"0"}:
            return True, "New or deleted ref: full regression required."
        git(repo, "cat-file", "-e", f"{revision}^{{commit}}")

    if event_name == "pull_request":
        # Compare the whole PR, not just its newest push or unrelated changes on the base.
        bases = git(repo, "merge-base", "--all", base, head).decode("ascii").splitlines()
        if len(bases) != 1:
            return True, "Ambiguous PR merge base: full regression required."
        base = bases[0]

    changed = git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--name-only",
        "--no-renames",
        "-z",
        base,
        head,
        "--",
    )
    # NUL delimiters preserve unusual filenames; disabling rename detection checks both paths.
    paths = [os.fsdecode(name) for name in changed.split(b"\0") if name]
    if not paths:
        return True, "Empty comparison: full regression required."
    if all(documentation_path(name) for name in paths):
        return False, f"Documentation-only comparison ({len(paths)} paths): expensive jobs skipped."
    return True, "Changes outside the documentation allowlist: full regression required."


def main() -> None:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        required, reason = regression_required(os.environ["GITHUB_EVENT_NAME"], event, Path.cwd())
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        required, reason = True, "Comparison unavailable: full regression required."
    print(reason)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"run_ci={str(required).lower()}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as output:
            output.write(f"### Regression scope\n\n{reason}\n")


if __name__ == "__main__":
    main()
