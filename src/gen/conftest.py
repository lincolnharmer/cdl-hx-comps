#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Shared setup for the generator's tests.

Tests marked `inputs` read three things that are not in the repo:
- the generator's source directory (cxf_source.py), which regen_cxf.sh rebuilds from MBL with modelica-json;
- MBL's CDL .mo files, which mbl_fetch.py downloads at MBL's release commit into its cache;
- MBL_DIR, a modelica-buildings clone at the pinned commit, which the round-trip tests read MBL's .mo from.
When any of them is missing or does not verify, the marked tests skip, and the run ends with a line naming what is
missing and how to get it, which prints even under -q. Every other test runs either way. A test that reads an input
but carries no mark fails without the inputs, so a missing mark shows up rather than passing unrun.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cxf_source  # noqa: E402
import mbl_fetch  # noqa: E402

_PROBLEMS = []
_SKIPPED = []


def _mbl_dir_problem():
    d = os.environ.get("MBL_DIR")
    commit = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))["mblCommit"]
    if not d or not (pathlib.Path(d) / "Buildings").is_dir():
        return "set MBL_DIR to a modelica-buildings clone at %s" % commit
    head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != commit:
        return "MBL_DIR %s is at %s, not %s" % (d, head or "no commit", commit)
    return None


def input_problems():
    """One line per input that is missing or does not verify; empty when every input is in place."""
    problems = []
    try:
        cxf_source.verify()
    except cxf_source.SourceError as e:
        problems.append(str(e).splitlines()[0])
    try:
        mbl_fetch.source_dir(fetch_missing=False)
    except mbl_fetch.MblSourceError as e:
        problems.append(str(e).splitlines()[0])
    p = _mbl_dir_problem()
    if p:
        problems.append(p)
    return problems


def pytest_configure(config):
    config.addinivalue_line("markers", "inputs: reads the generator source, the MBL .mo cache or MBL_DIR")


def pytest_collection_modifyitems(config, items):
    marked = [item for item in items if item.get_closest_marker("inputs")]
    if not marked:
        return
    _PROBLEMS[:] = input_problems()
    if not _PROBLEMS:
        return
    skip = pytest.mark.skip(reason="the generator's inputs are missing: " + "; ".join(_PROBLEMS))
    for item in marked:
        item.add_marker(skip)
    _SKIPPED[:] = marked


def pytest_terminal_summary(terminalreporter):
    if _SKIPPED:
        terminalreporter.write_line("%d tests that read the generator's inputs were skipped:" % len(_SKIPPED),
                                    yellow=True)
        for p in _PROBLEMS:
            terminalreporter.write_line("  " + p, yellow=True)


@pytest.fixture(scope="session")
def mbl_cdl():
    """MBL's CDL source, from the cache mbl_fetch.py downloads into."""
    return mbl_fetch.source_dir(fetch_missing=False)
