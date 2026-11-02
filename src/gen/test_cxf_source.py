"""Tests for the source directory check (cxf_source.py). Run from the repo root: python -X utf8 -m pytest src/gen -q"""
import json
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cxf_source  # noqa: E402
import generate  # noqa: E402


def _tree(tmp_path, files):
    src = tmp_path / "src"
    for rel, data in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    man = {"files": {rel: cxf_source.sha256(data) for rel, data in files.items()}}
    return src, man


FILES = {"kw.cdl/cdl-elementary.jsonld": b"{}\n", "kw.cdl.g36.common/cxf/Generic/A.jsonld": b"{\"a\": 1}\n"}


def test_a_directory_that_matches_the_manifest_verifies(tmp_path):
    src, man = _tree(tmp_path, FILES)
    assert cxf_source.verify(src, man) == src


@pytest.mark.parametrize("change, want", [
    ("missing", "kw.cdl.g36.common/cxf/Generic/A.jsonld: missing"),
    ("differs", "kw.cdl.g36.common/cxf/Generic/A.jsonld: sha256 "),
    ("unlisted", "kw.cdl.g36.common/cxf/Generic/B.jsonld: a file the manifest does not list"),
])
def test_a_file_that_differs_from_the_manifest_stops_naming_the_file(tmp_path, change, want):
    # Wrong behavior caught: generation reading inputs other than the ones the manifest pins, or a refusal that does
    # not say which file is wrong.
    src, man = _tree(tmp_path, FILES)
    f = src / "kw.cdl.g36.common/cxf/Generic/A.jsonld"
    if change == "missing":
        f.unlink()
    elif change == "differs":
        f.write_bytes(b"{\"a\": 2}\n")
    else:
        f.with_name("B.jsonld").write_bytes(b"{}\n")
    with pytest.raises(cxf_source.SourceError) as e:
        cxf_source.verify(src, man)
    assert want in str(e.value) and not isinstance(e.value, cxf_source.SourceAbsent)


def test_no_source_directory_is_absent_and_names_the_command(tmp_path):
    # Wrong behavior caught: a missing source read as an empty one, so generation writes libs with nothing in them.
    with pytest.raises(cxf_source.SourceAbsent, match="regen_cxf.sh"):
        cxf_source.verify(tmp_path / "nothing", {"files": {}})


def test_the_manifest_pins_the_stamp_and_every_input():
    # Wrong behavior caught: a manifest written for other pins than stamp.json's, or one missing the elementary CXF or
    # a G36 lib's inputs.
    man = cxf_source.manifest()
    stamp = generate.load_stamp()
    assert (man["mbl"], man["mblCommit"], man["modelicaJson"]) == (stamp["mbl"], stamp["mblCommit"],
                                                                     stamp["modelicaJson"])
    assert "kw.cdl/cdl-elementary.jsonld" in man["files"]
    for lib in generate.G36_LIBS:
        for kind in ("cxf", "json"):
            assert any(r.startswith("%s/%s/" % (lib, kind)) for r in man["files"]), (lib, kind)


@pytest.mark.skipif(not os.environ.get("HAYSTACK_XETO_SRC"),
                    reason="HAYSTACK_XETO_SRC names no Project Haystack xeto src/xeto directory")
def test_the_pinned_ph_tags_are_what_the_source_declares():
    # Wrong behavior caught: a tag table edited by hand, or left behind when the pinned commit moves.
    want = generate.ph_tags(os.environ["HAYSTACK_XETO_SRC"])
    assert json.loads(generate.PH_TAGS.read_text(encoding="utf-8"))["tags"] == want
