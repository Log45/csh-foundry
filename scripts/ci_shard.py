"""Partition the collected regression suite without maintaining feature/file allowlists."""

import pytest


def shard(value: str) -> tuple[int, int]:
    try:
        index, total = map(int, value.split("/"))
    except ValueError as exc:
        raise pytest.UsageError("--ci-shard must be INDEX/TOTAL (zero-based)") from exc
    if total < 1 or not 0 <= index < total:
        raise pytest.UsageError("--ci-shard requires 0 <= INDEX < TOTAL")
    return index, total


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--ci-shard", type=shard, help="Run a zero-based INDEX/TOTAL collection shard")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    selection = config.getoption("--ci-shard")
    if selection is None:
        return
    index, total = selection
    selected, deselected = [], []
    for position, item in enumerate(items):
        (selected if position % total == index else deselected).append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
