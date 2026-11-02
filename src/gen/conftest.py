"""Shared setup for the generator's tests.

The tests read three things that are not in the repo, and the session stops before any test runs when one is
missing or does not verify, naming what to do:
- the generator's source directory (cxf_source.py), which regen_cxf.sh rebuilds from MBL with modelica-json;
- MBL's CDL .mo files, which mbl_fetch.py downloads at the release tag into its cache;
- MBL_DIR, a modelica-buildings clone at the pinned commit, which the round-trip tests read MBL's .mo from.
A missing input stops the run rather than skipping tests, so a run cannot pass with most of its tests unrun.
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


def _mbl_dir_problem():
    d = os.environ.get("MBL_DIR")
    commit = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))["mblCommit"]
    if not d or not (pathlib.Path(d) / "Buildings").is_dir():
        return "set MBL_DIR to a modelica-buildings clone at %s" % commit
    head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != commit:
        return "MBL_DIR %s is at %s, not %s" % (d, head or "no commit", commit)
    return None


def pytest_sessionstart(session):
    problems = []
    try:
        cxf_source.verify()
    except cxf_source.SourceError as e:
        problems.append(str(e))
    try:
        mbl_fetch.source_dir(fetch_missing=False)
    except mbl_fetch.MblSourceError as e:
        problems.append(str(e))
    p = _mbl_dir_problem()
    if p:
        problems.append(p)
    if problems:
        pytest.exit("the generator's tests need their inputs:\n  " + "\n  ".join(problems), returncode=4)


@pytest.fixture(scope="session")
def mbl_cdl():
    """MBL's CDL source, from the cache mbl_fetch.py downloads into, verified at session start."""
    return mbl_fetch.source_dir(fetch_missing=False)
