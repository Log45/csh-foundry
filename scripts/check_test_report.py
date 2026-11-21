"""Reject missing, empty, failed or skipped JUnit results in required CI suites."""

import argparse
from pathlib import Path
from xml.etree import ElementTree

# Existing strict xfail documents a dependency incompatibility, not a missing prerequisite.
# Match the exact identity, pytest result type and reason; ordinary skips still fail.
KNOWN_XFAIL = (
    "services.api.tests.test_fixtures",
    "test_raw_pyshacl_compatibility",
    "Raw pySHACL/RDFLib simple/xsd:string mismatch; see semantic-compatibility.md",
)


def known_xfail(case: ElementTree.Element) -> bool:
    skipped = case.find("skipped")
    return (
        skipped is not None
        and skipped.get("type") == "pytest.xfail"
        and (case.get("classname"), case.get("name"), skipped.get("message")) == KNOWN_XFAIL
        and case.find("failure") is None
        and case.find("error") is None
    )


def check_report(path: Path) -> int:
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError(f"No tests executed: {path}")
    expected = [case for case in cases if known_xfail(case)]
    invalid = [
        case
        for case in cases
        if not known_xfail(case)
        and any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
    ]
    if invalid:
        names = ", ".join(case.get("name", "unnamed") for case in invalid)
        raise ValueError(f"Required tests failed or skipped: {names}")
    for case in expected:
        print(f"EXPECTED FAILURE (not PASS): {case.get('name')}: {KNOWN_XFAIL[2]}")
    passed = len(cases) - len(expected)
    if not passed:
        raise ValueError(f"No passing tests executed: {path}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        count = check_report(args.report)
    except (OSError, ElementTree.ParseError, ValueError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    print(f"PASS: {count} passing tests; no unexpected failures or skips ({args.report})")


if __name__ == "__main__":
    main()
