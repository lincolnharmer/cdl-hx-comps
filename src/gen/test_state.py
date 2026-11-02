#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Tests for kw.cdl's state facts: cdlState, cdlStateInit, cdlStateInitBasis and cdlStateBasis on every elementary
class. Run from the repo root: python -X utf8 -m pytest src/gen -q

The generator reads MBL's .mo through mo_state.py. These tests read it a second way, with regular expressions and
mo_reader.py's components, and share no parser with mo_state.py, so a reader that drops a construct disagrees here.
"""
import hashlib
import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIBS = ROOT / "src" / "xeto"
sys.path.insert(0, str(HERE))

import cxf_source  # noqa: E402

SRC = cxf_source.source_root()

import check_open_libs  # noqa: E402
import generate  # noqa: E402
import mbl_fetch  # noqa: E402
import mo_reader  # noqa: E402
import mo_state  # noqa: E402

MBL_DIR = pathlib.Path(os.environ.get("MBL_DIR", ""))   # an MBL clone at the pin; conftest.py checks it
CDL = generate.CDL_PREFIX
STATES = ("stateful", "stateless", "undecided")
INITS = ("readsInput", "noInput", "undecided")
INIT_BASES = ("noInputConnector", "preDelayed", "parameterInit", "undecided")
TAGS = ("cdlState", "cdlStateInit", "cdlStateInitBasis", "cdlStateBasis")


def elementary():
    """The 132 elementary class paths, from the pinned CXF (not from the pins, which these tests check)."""
    doc = json.loads((SRC / "kw.cdl/cdl-elementary.jsonld").read_text(encoding="utf-8"))
    return sorted(n["@id"][len("S231:"):] for n in doc["@graph"] if n.get("@type") == "S231:ElementaryBlock")


# The elementary specs retired: each class's facts now ride its CdlClass instance in kw.cdl/classes.xeto (or its
# CdlRefusal), as the fields state, stateInit, stateInitBasis and stateBasis. They read back under the meta names.
FIELD_TAG = {"state": "cdlState", "stateInit": "cdlStateInit", "stateInitBasis": "cdlStateInitBasis",
             "stateBasis": "cdlStateBasis"}
INSTANCE_RE = re.compile(r"^@cdl-(\w+): CdlClass \{\n(.*?)^\}", re.M | re.S)
FIELD_RE = re.compile(r'^  (\w+): "((?:[^"\\]|\\.)*)"$', re.M)
REFUSAL_RE = re.compile(r"^    CdlRefusal \{(.*)\}$", re.M)


def spec_facts(text):
    """{class path: its facts under the meta names, with cdlClass} of every class in a generated classes.xeto text."""
    out = {}
    for m in INSTANCE_RE.finditer(text):
        fields = {k: json.loads('"%s"' % v) for k, v in FIELD_RE.findall(m.group(2))}
        meta = {FIELD_TAG[k]: v for k, v in fields.items() if k in FIELD_TAG}
        meta["cdlClass"] = fields["cdlClass"]
        out[meta["cdlClass"]] = meta
    for m in REFUSAL_RE.finditer(text):
        meta = generate._meta("<" + m.group(1) + ">")[0]
        facts = {FIELD_TAG[k]: v for k, v in meta.items() if k in FIELD_TAG}
        facts["cdlClass"] = meta["cdlClass"]
        out[facts["cdlClass"]] = facts
    return out


def blocks_text():
    return (LIBS / "kw.cdl" / "classes.xeto").read_text(encoding="utf-8")


# ---- the independent reading ----

CONSTRUCTS = {"pre": r"\bpre\s*\(", "edge": r"\bedge\s*\(", "change": r"\bchange\s*\(", "when": r"\bwhen\b",
              "der": r"\bder\s*\(", "delay": r"\bdelay\s*\(", "sample": r"\bsample\s*\(", "reinit": r"\breinit\s*\(",
              "discrete": r"\bdiscrete\b", "initialParameter": r"\bfixed\s*=\s*false\b"}


def _code(text):
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def independent(cls, memo=None):
    """(state, own constructs, instance names) of `cls` read from MBL's working tree: a construct anywhere in the
    file's code (its local classes included), or a CDL instance mo_reader finds whose class reads stateful. An
    instance of a class outside CDL that is not local to the file is unread."""
    memo = {} if memo is None else memo
    if cls in memo:
        return memo[cls]
    text = (MBL_DIR / (cls.replace(".", "/") + ".mo")).read_text(encoding="utf-8")
    code = _code(text)
    own = {k for k, rx in CONSTRUCTS.items() if re.search(rx, code)}
    stateful_insts, unread = set(), False
    for name, comp in mo_reader.read(text, cls, MBL_DIR)["components"].items():
        sub = comp["class"]
        if sub.startswith(CDL):
            if independent(sub, memo)[0] == "stateful":
                stateful_insts.add(name)
        elif "." in sub:
            unread = True
    state = "stateful" if own or stateful_insts else ("undecided" if unread else "stateless")
    memo[cls] = (state, own, set(mo_reader.read(text, cls, MBL_DIR)["components"]), stateful_insts)
    return memo[cls]


def fact_violations(text):
    """Every way the facts in a blocks.xeto text disagree with the independent reading, or break the fact's shape."""
    out, memo = [], {}
    facts = spec_facts(text)
    for cls in elementary():
        meta = facts.get(cls)
        if meta is None:
            out.append("%s: no CdlClass instance or refusal" % cls)
            continue
        state = meta.get("cdlState")
        if state not in STATES:
            out.append("%s: carries no cdlState in %s (%r)" % (cls, STATES, state))
            continue
        init, basis = meta.get("cdlStateInit"), meta.get("cdlStateBasis")
        if (state == "stateful") != (init is not None) or init is not None and init not in INITS:
            out.append("%s: cdlStateInit %r on a %s class" % (cls, init, state))
        why = meta.get("cdlStateInitBasis")
        if (init == "noInput") != (why is not None) or why is not None and why not in INIT_BASES:
            out.append("%s: cdlStateInitBasis %r on a class whose cdlStateInit is %r" % (cls, why, init))
        if (state == "stateless") != (basis is None):
            out.append("%s: cdlStateBasis %r on a %s class" % (cls, basis, state))
        want, own, comps, stateful_insts = independent(cls, memo)
        if state != want:
            out.append("%s: cdlState is %s, MBL's source reads %s" % (cls, state, want))
        for item in basis.split("; ") if basis else []:
            if item.startswith("unread: "):
                continue
            m = re.match(r"instance (\w+)( \(conditional\))?$", item)
            if m:
                if m.group(1) not in comps:
                    out.append("%s: basis names instance %s, which MBL's source does not declare" % (cls, m.group(1)))
            elif item not in own:
                out.append("%s: basis names %s, which MBL's source does not use" % (cls, item))
    return out


# ---- the generated lib ----

def test_every_elementary_class_carries_one_state_fact_and_agrees_with_mbl():
    # Wrong behavior caught: a class with no fact, a fact outside its vocabulary, an init fact on a class that is not
    # stateful, or a verdict the independent reading of MBL's source contradicts.
    facts = spec_facts(blocks_text())
    assert len(facts) == 132
    assert fact_violations(blocks_text()) == []


def _replace_head(text, spec, new_tags):
    """The classes.xeto text with the state fields of @cdl-<spec> replaced by `new_tags`, written in the meta form
    (', cdlState:"stateful", cdlStateInit:"readsInput'), so a planted fact reads as the generator would write it."""
    m = re.search(r"^@cdl-%s: CdlClass \{\n(.*?)^\}" % spec, text, re.M | re.S)
    if m is None:
        raise AssertionError("no instance " + spec)
    tag_field = {v: k for k, v in FIELD_TAG.items()}
    body = "".join(l + "\n" for l in m.group(1).splitlines() if l.split(":")[0].strip() not in FIELD_TAG)
    for k, v in re.findall(r'(\w+):"([^"]*)"', new_tags):
        body += '  %s: "%s"\n' % (tag_field[k], v)
    return text[:m.start(1)] + body + text[m.end(1):]


def test_a_planted_stateless_class_marked_stateful_is_caught():
    # The check's red condition: Reals.Add (y = k1*u1 + k2*u2, Reals/Add.mo) claimed stateful.
    planted = _replace_head(blocks_text(), "RealsAdd", ', cdlState:"stateful", cdlStateInit:"readsInput", '
                                                       'cdlStateBasis:"pre"')
    bad = fact_violations(planted)
    assert any(b.startswith(CDL + "Reals.Add: cdlState is stateful, MBL's source reads stateless") for b in bad), bad
    assert any(b.startswith(CDL + "Reals.Add: basis names pre") for b in bad), bad


def test_a_planted_stateful_class_marked_stateless_is_caught():
    # The check's red condition: Logical.Latch (when {clr, u} then y = not clr and u, Logical/Latch.mo) claimed
    # stateless, which would let a native latch run with no restore and drop a held alarm on every rebuild.
    planted = _replace_head(blocks_text(), "LogicalLatch", ', cdlState:"stateless"')
    bad = fact_violations(planted)
    assert any(b.startswith(CDL + "Logical.Latch: cdlState is stateless, MBL's source reads stateful") for b in bad), bad


def test_a_planted_class_with_no_fact_is_caught():
    # The check's red condition: a class whose fact went missing. A reader treats it as not known stateless, which
    # fails closed, but the generated lib promises a fact on all 132.
    planted = _replace_head(blocks_text(), "RealsAbs", "")
    bad = fact_violations(planted)
    assert any(b.startswith(CDL + "Reals.Abs: carries no cdlState") for b in bad), bad


def test_a_planted_init_fact_on_a_stateless_class_is_caught():
    planted = _replace_head(blocks_text(), "RealsAbs", ', cdlState:"stateless", cdlStateInit:"noInput"')
    assert any(b.startswith(CDL + "Reals.Abs: cdlStateInit") for b in fact_violations(planted))


# Readings of MBL 14.0.0 that the init fact rests on, each with the line it rests on. readsInput: at least one output's
# value at the initial instant reads an input connector, in every configuration.
INIT = {
    "Logical.TrueDelay": "readsInput",        # when initial() then y = if not (delayOnInit and delayTime > 0) then u
    "Reals.Greater": "readsInput",            # GreaterWithHysteresis: y = not pre(y) and u1 > u2 or ..., at t = 0
    "Reals.GreaterThreshold": "readsInput",   # the same, with u > t
    "Reals.Less": "readsInput",
    "Reals.LessThreshold": "readsInput",
    "Logical.Latch": "readsInput",            # initial equation y = not clr and u
    "Discrete.Sampler": "readsInput",         # when {sampleTrigger, initial()} then y = u
    "Discrete.FirstOrderHold": "readsInput",  # pre(pre_uSample) = u, and y = pre_uSample + pre(c)*(time - tSample)
    "Logical.Timer": "readsInput",            # y = if u then time - entryTime else 0.0; passed alone starts at t <= 0
    "Logical.TimerAccumulating": "readsInput",   # y = if u then yAcc + time - entryTime else yAcc
    "Logical.Edge": "readsInput",             # y = edge(u), which is u and not pre(u): it reads u now
    "Logical.FallingEdge": "readsInput",      # y = edge(not u)
    "Logical.Change": "readsInput",           # y = change(u), which is u <> pre(u)
    "Discrete.UnitDelay": "noInput",          # initial equation y = y_start; u is read only when sampleTrigger fires
    "Logical.Sources.SampleTrigger": "noInput",   # no input connector: y = sample(t0, period)
    "Logical.Pre": "noInput",                 # y = pre(u), u(start=pre_u_start): the initial output is the parameter
    "Discrete.TriggeredSampler": "noInput",   # initial equation y = y_start
    "Reals.IntegratorWithReset": "noInput",   # initial equation y = y_start
}
# Why a noInput class reads no input at the initial instant, each with its MBL line.
INIT_BASIS = {
    "Logical.Sources.SampleTrigger": "noInputConnector",   # its only connector is the output y
    "Reals.Sources.CalendarTime": "noInputConnector",
    "Discrete.UnitDelay": "preDelayed",       # when sampleTrigger then y = pre(u_internal); u_internal = u
    "Logical.Pre": "preDelayed",              # y = pre(u)
    "Discrete.ZeroOrderHold": "preDelayed",   # y = pre(ySample), "to break potential algebraic loops"
    "Discrete.TriggeredSampler": "parameterInit",   # when trigger then y = u: u read now, after the instant
    "Integers.OnCounter": "parameterInit",    # when {trigger, reset} then y = if reset then y_start else pre(y) + 1
    "Reals.MovingAverage": "parameterInit",   # y from mu, and der(mu) = u: an integral, not a pre() delay
}


def test_the_mbl_cited_readings_hold():
    # Wrong behavior caught: an init verdict that contradicts MBL's own equations. "Every output must read an input"
    # would flip Timer and TimerAccumulating, whose passed output starts at t <= 0; edge() and change() read only
    # as the previous value would flip Edge, FallingEdge and Change. Both flips were mutants the suite missed.
    facts = spec_facts(blocks_text())
    for c, init in INIT.items():
        assert facts[CDL + c].get("cdlStateInit") == init, c
    for c, why in INIT_BASIS.items():
        assert facts[CDL + c].get("cdlStateInitBasis") == why, c


def test_the_no_input_classes_split_nine_three_five():
    # Wrong behavior caught: the split drifting from a hand reading of all 17 noInput classes in MBL 14.0.0: nine
    # sources with no input connector, three that delay every output by pre() (MBL's loop-breaking idiom), and five
    # whose inputs are read only after the initial instant.
    got = {}
    for meta in spec_facts(blocks_text()).values():
        if meta.get("cdlStateInit") == "noInput":
            got[meta["cdlStateInitBasis"]] = got.get(meta["cdlStateInitBasis"], 0) + 1
    assert got == {"noInputConnector": 9, "preDelayed": 3, "parameterInit": 5}


# The forms a basis item takes (mo_state.facts): a construct, a stateful instance, or a part of the source left unread.
BASIS_ITEM = re.compile(r"(?:%s)|instance \w+(?: \(conditional\))?|unread: (?:it is impure|its function \w+ is impure"
                        r"|a call to [\w.]+, which this reader has not classified|instance \w+ is of [\w.]+, which the"
                        r" pinned source does not hold|instance \w+(?: \(conditional\))? is of an undecided class"
                        r"|the source does not parse \(.*\))" % "|".join(CONSTRUCTS))


def test_the_facts_are_drawn_from_their_own_vocabulary():
    # Wrong behavior caught: the open fact carrying anything but CDL's own reading (a kernel, a runtime tag, an
    # engine's own spec spelt into a basis). Each value is held to the fact's own vocabulary, an allow-list, so the
    # check names nothing outside CDL.
    for meta in spec_facts(blocks_text()).values():
        assert meta["cdlState"] in STATES, meta["cdlClass"]
        assert meta.get("cdlStateInit", INITS[0]) in INITS, meta["cdlClass"]
        assert meta.get("cdlStateInitBasis", INIT_BASES[0]) in INIT_BASES, meta["cdlClass"]
        for item in meta.get("cdlStateBasis", "pre").split("; "):
            assert BASIS_ITEM.fullmatch(item), (meta["cdlClass"], item)


def test_a_planted_basis_item_outside_the_vocabulary_is_caught():
    # Wrong behavior caught: a basis allow-list so loose that a runtime word in a basis would pass it.
    for bad in ("acmeKernel", "instance x via kernel", "unread: see the runtime"):
        assert not BASIS_ITEM.fullmatch(bad), bad


def test_the_new_tags_are_kw_cdls_own():
    # Wrong behavior caught: a state tag that kw.cdl does not declare, so the fact reads as no meta at all.
    declared, _ = check_open_libs.meta_tags(LIBS / "kw.cdl", "kw.cdl")
    for tag in TAGS:
        assert tag in declared, tag


# ---- the source: MBL's .mo, fetched at the tag and verified ----

MANIFEST = mbl_fetch.manifest()


def test_the_manifest_lists_exactly_the_elementary_classes():
    # Wrong behavior caught: a class whose .mo the manifest does not pin (it would get no fact) or a stray entry.
    listed = sorted(mo_state.path_of(p[len(mbl_fetch.CDL_DIR) + 1:]) for p in MANIFEST["files"])
    assert all(p.startswith(mbl_fetch.CDL_DIR + "/") and p.endswith(".mo") for p in MANIFEST["files"])
    assert listed == elementary()
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in MANIFEST["files"].values())


def test_the_manifest_is_the_release_the_stamp_pins():
    # Wrong behavior caught: the source fetched at a tag other than the release kw.cdl names in every header, so the
    # facts would describe a different MBL than the classes.
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    assert (MANIFEST["mbl"], MANIFEST["tag"], MANIFEST["commit"]) == (stamp["mbl"], "v" + stamp["mbl"], stamp["mblCommit"])
    assert MANIFEST["repo"] == "https://github.com/lbl-srg/modelica-buildings"
    # By the commit, which cannot move, not by the tag, which can.
    assert mbl_fetch.RAW == "https://raw.githubusercontent.com/lbl-srg/modelica-buildings/{commit}/{path}"
    assert re.fullmatch(r"[0-9a-f]{40}", MANIFEST["commit"])


def test_every_hash_is_mbl_source_at_the_tag():
    # Wrong behavior caught: a hash taken from an edited file, from another commit or from a CRLF checkout, so the
    # fetch would refuse MBL's own file or accept another. MBL_DIR is a checkout holding the tag.
    assert (MBL_DIR / "Buildings").is_dir(), "set MBL_DIR to an MBL checkout at the pin; missing " + str(MBL_DIR)
    peeled = subprocess.run(["git", "-C", str(MBL_DIR), "rev-parse", MANIFEST["commit"] + "^{commit}"],
                            capture_output=True, check=True, text=True).stdout.strip()
    assert peeled == MANIFEST["commit"]
    for path, want in MANIFEST["files"].items():
        got = subprocess.run(["git", "-C", str(MBL_DIR), "show", MANIFEST["commit"] + ":" + path],
                             capture_output=True, check=True).stdout
        assert mbl_fetch.sha256(got) == want, path


def test_no_mbl_source_is_kept_in_the_repo():
    # Wrong behavior caught: MBL's .mo back in the repo, vendored or regenerated into it, when nothing MBL-authored
    # is kept in the repo. Every file git tracks and every file on disk under the repo is checked.
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, check=True, text=True).stdout
    assert [f for f in tracked.splitlines() if f.lower().endswith(".mo")] == []
    assert [f for f in ROOT.rglob("*.mo") if ".git" not in f.parts] == []
    assert not (HERE / "mbl-source").exists()


def test_the_cache_is_mbl_at_the_tag_byte_for_byte(mbl_cdl):
    # Wrong behavior caught: the generator reading a cache that differs from the manifest. source_dir verified it;
    # this reads it again here so the check does not rest on the code it checks.
    for path, want in MANIFEST["files"].items():
        assert hashlib.sha256((mbl_cdl.parents[3] / path).read_bytes()).hexdigest() == want, path


def _fake_mbl(tmp_path, files):
    """A manifest for `files` ({name: bytes} under the CDL directory) and a download that serves them by URL."""
    man = {"tag": "vT", "commit": "c" * 40,
           "files": {"%s/%s" % (mbl_fetch.CDL_DIR, n): mbl_fetch.sha256(b) for n, b in files.items()}}
    served = {mbl_fetch.RAW.format(commit="c" * 40, path="%s/%s" % (mbl_fetch.CDL_DIR, n)): b for n, b in files.items()}
    calls = []

    def download(url):
        calls.append(url)
        if url not in served:
            raise mbl_fetch.MblSourceError("could not download %s: 404" % url)
        return served[url]
    return man, served, download, calls


def test_a_download_that_differs_from_its_hash_is_refused_and_not_written(tmp_path):
    # Wrong behavior caught: a changed upstream file, a proxy's error page or a truncated read accepted as MBL's.
    man, served, download, _ = _fake_mbl(tmp_path, {"A/X.mo": b"block X end X;\n"})
    url = next(iter(served))
    served[url] = b"<html>rate limited</html>"
    with pytest.raises(mbl_fetch.MblSourceError, match=r"A/X\.mo .*sha256.*Nothing was written"):
        mbl_fetch.fetch(tmp_path / "c", man, download)
    assert not (tmp_path / "c" / mbl_fetch.CDL_DIR / "A" / "X.mo").exists()


def test_a_failed_download_is_refused_by_name(tmp_path):
    man, served, download, _ = _fake_mbl(tmp_path, {"A/X.mo": b"x\n", "A/Y.mo": b"y\n"})
    del served[mbl_fetch.RAW.format(commit="c" * 40, path=mbl_fetch.CDL_DIR + "/A/Y.mo")]
    with pytest.raises(mbl_fetch.MblSourceError, match=r"A/Y\.mo"):
        mbl_fetch.fetch(tmp_path / "c", man, download)


def test_a_cache_that_verifies_downloads_nothing_and_a_tampered_file_is_fetched_again(tmp_path, capsys):
    # Wrong behavior caught: a fetch that trusts a cached file without its hash, or one that downloads everything
    # every time (so regeneration needs the network even with a good cache).
    man, _, download, calls = _fake_mbl(tmp_path, {"A/X.mo": b"x\n", "A/Y.mo": b"y\n"})
    c = mbl_fetch.fetch(tmp_path / "c", man, download)
    assert len(calls) == 2
    mbl_fetch.fetch(c, man, download)
    assert len(calls) == 2
    (c / mbl_fetch.CDL_DIR / "A" / "Y.mo").write_bytes(b"edited\n")
    capsys.readouterr()
    mbl_fetch.fetch(c, man, download)
    said = capsys.readouterr()
    # The repair is named, with both hashes, never done silently.
    assert "A/Y.mo in the cache has sha256 %s, the manifest pins" % mbl_fetch.sha256(b"edited\n") in said.err
    assert "1 of them replacing a cached file that did not match: %s/A/Y.mo" % mbl_fetch.CDL_DIR in said.out
    assert len(calls) == 3 and (c / mbl_fetch.CDL_DIR / "A" / "Y.mo").read_bytes() == b"y\n"


class _Resp:
    """A urlopen response: `body`, and the Content-Length a server claims for it (None for none)."""

    def __init__(self, body, length=None, cut=False):
        self.body, self.cut = body, cut
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self.cut:
            raise http.client.IncompleteRead(self.body[:3], len(self.body) - 3)
        return self.body


@pytest.mark.parametrize("resp", [_Resp(b"block X end X;\n", cut=True), _Resp(b"block X", length=15)],
                         ids=["IncompleteRead", "shorter than Content-Length"])
def test_a_body_cut_short_is_a_failed_download_not_a_file(monkeypatch, resp):
    # Wrong behavior caught: http.client.IncompleteRead is not an OSError, so it escaped the retry
    # and MblSourceError; and a body shorter than the server's Content-Length read as a whole file.
    monkeypatch.setattr(mbl_fetch.time, "sleep", lambda s: None)
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        return resp
    with pytest.raises(mbl_fetch.MblSourceError, match=r"after 3 tries: IncompleteRead"):
        mbl_fetch._download("https://example.invalid/A/X.mo", opener)
    assert len(calls) == 3


def test_a_whole_body_is_returned_as_it_came(monkeypatch):
    body = b"block X end X;\n"
    assert mbl_fetch._download("https://example.invalid/A/X.mo", lambda req, timeout: _Resp(body, len(body))) == body
    assert mbl_fetch._download("https://example.invalid/A/X.mo", lambda req, timeout: _Resp(body)) == body


@pytest.mark.parametrize("fault,match", [
    ("missing", r"A/Y\.mo: missing"),
    ("edited", r"A/Y\.mo: sha256 [0-9a-f]{64}, the manifest pins"),
    ("stray", r"A/Z\.mo: a \.mo the manifest does not list"),
])
def test_a_cache_that_does_not_verify_fails_without_fetching(tmp_path, fault, match):
    # Wrong behavior caught: the tests or a --no-fetch regeneration reading a partial, edited or padded cache, or
    # reading it as absent and skipping. Only a cache with no .mo at all is absent.
    man, _, download, calls = _fake_mbl(tmp_path, {"A/X.mo": b"x\n", "A/Y.mo": b"y\n"})
    c = mbl_fetch.fetch(tmp_path / "c", man, download)
    y = c / mbl_fetch.CDL_DIR / "A" / "Y.mo"
    if fault == "missing":
        y.unlink()
    elif fault == "edited":
        y.write_bytes(b"edited\n")
    else:
        (y.parent / "Z.mo").write_bytes(b"z\n")
    with pytest.raises(mbl_fetch.MblSourceError, match=match) as e:
        mbl_fetch.source_dir(fetch_missing=False, cache=c, man=man)
    assert not isinstance(e.value, mbl_fetch.MblSourceAbsent)
    with pytest.raises(mbl_fetch.MblSourceAbsent, match=r"run: python -X utf8 src/gen/mbl_fetch\.py"):
        mbl_fetch.source_dir(fetch_missing=False, cache=tmp_path / "empty", man=man)


def test_generation_without_the_cache_and_without_fetching_stops_naming_the_fetch(tmp_path, monkeypatch):
    # Wrong behavior caught: a --no-fetch regeneration writing kw.cdl with no state facts, or with stale ones, when
    # the source is not there. It must stop and say how to get it.
    monkeypatch.setenv("KW_CDL_MBL_CACHE", str(tmp_path / "nothing"))
    with pytest.raises(mbl_fetch.MblSourceAbsent, match="mbl_fetch.py"):
        generate.main(["--out", str(tmp_path / "out"), "--no-fetch"])
    assert not (tmp_path / "out" / "kw.cdl" / "blocks.xeto").exists()


def test_a_missing_class_refuses_generation_by_name(tmp_path, mbl_cdl):
    # Wrong behavior caught: a class with no source generated with no fact, or with a guessed one.
    shutil.copytree(mbl_cdl, tmp_path / "mo")
    (tmp_path / "mo" / "Logical" / "Latch.mo").unlink()
    with pytest.raises(generate.CxfError, match="Logical.Latch"):
        generate.state_facts(tmp_path / "mo", elementary())


def test_a_stray_class_refuses_generation_by_name(tmp_path, mbl_cdl):
    shutil.copytree(mbl_cdl, tmp_path / "mo")
    (tmp_path / "mo" / "Logical" / "Bogus.mo").write_text("block Bogus\nend Bogus;\n", encoding="utf-8")
    with pytest.raises(generate.CxfError, match="Logical.Bogus"):
        generate.state_facts(tmp_path / "mo", elementary())


# ---- the reader, on planted classes ----

def _facts(**classes):
    """Facts of planted classes, each a .mo body inside `block <Name> ... end <Name>;`, at CDL.Plant.<Name>."""
    src = {}
    for name, body in classes.items():
        src[CDL + "Plant." + name] = "within Buildings.Controls.OBC.CDL.Plant;\nblock %s\n%s\nend %s;\n" % (name, body,
                                                                                                         name)
    return mo_state.facts(src)


IO = """  Buildings.Controls.OBC.CDL.Interfaces.RealInput u "Input";
  Buildings.Controls.OBC.CDL.Interfaces.RealOutput y "Output";"""


@pytest.mark.parametrize("body,basis", [
    ("equation\n  y = 2*u;", None),
    ("equation\n  y = Modelica.Math.sin(u) + time;", None),
    ("  parameter Real k = 1;\nequation\n  y = if u > k then u else k;", None),
])
def test_a_planted_stateless_class_reads_stateless(body, basis):
    # Wrong behavior caught: a function call, a reference to time or an if-expression read as state.
    f = _facts(P=IO + "\n" + body)[CDL + "Plant.P"]
    assert (f.state, f.init, f.basis) == ("stateless", None, [])


@pytest.mark.parametrize("body,construct", [
    ("equation\n  y = pre(u);", "pre"),
    ("  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput b;\nequation\n  y = if edge(b) then u else 0;", "edge"),
    ("equation\n  when u > 1 then\n    y = u;\n  end when;", "when"),
    ("  Real x;\nequation\n  der(x) = u;\n  y = x;", "der"),
    ("equation\n  y = delay(u, 10);", "delay"),
    ("  parameter Real t0(fixed=false);\ninitial equation\n  t0 = time;\nequation\n  y = u + t0;", "initialParameter"),
    ("  discrete Real x;\nequation\n  y = u;", "discrete"),
    ("  Boolean s;\nequation\n  s = sample(0, 1);\n  y = u;", "sample"),
    ("  Boolean s = sample(0, 1);\nequation\n  y = u;", "sample"),
    ("  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput b;\nequation\n  y = if change(b) then u else 0;", "change"),
    ("  Real x;\nequation\n  der(x) = u;\n  when u > 1 then\n    reinit(x, 0);\n  end when;\n  y = x;", "reinit"),
])
def test_a_planted_stateful_class_reads_stateful_naming_its_construct(body, construct):
    # Wrong behavior caught: one of the state constructs missed, so a stateful class reads stateless and a native
    # binding of it skips the state gate.
    f = _facts(P=IO + "\n" + body)[CDL + "Plant.P"]
    assert f.state == "stateful" and construct in f.basis, f


@pytest.mark.parametrize("body,init", [
    ("  parameter Real y_start = 0;\ninitial equation\n  y = y_start;\nequation\n  when u > 1 then\n    y = u;\n"
     "  end when;", "noInput"),
    ("initial equation\n  y = u;\nequation\n  when u > 1 then\n    y = u;\n  end when;", "readsInput"),
    ("equation\n  when {initial(), u > 1} then\n    y = u;\n  end when;", "readsInput"),
    ("equation\n  when u > 1 then\n    y = u;\n  end when;", "noInput"),
    ("  Real x;\ninitial equation\n  pre(x) = u;\nequation\n  when u > 1 then\n    x = u;\n  end when;\n  y = x;",
     "readsInput"),
])
def test_the_init_fact_reads_the_initial_system(body, init):
    # Wrong behavior caught: a when body counted as active at the initial instant (UnitDelay would read readsInput and
    # pass the state gate although it emits y_start before any input), or an initial equation, an
    # initial() branch or a held pre() value that reads an input missed.
    f = _facts(P=IO + "\n" + body)[CDL + "Plant.P"]
    assert (f.state, f.init) == ("stateful", init), f


def test_a_stateful_instance_makes_its_container_stateful_and_carries_its_init():
    held = IO + "\ninitial equation\n  y = u;\nequation\n  when u > 1 then\n    y = u;\n  end when;"
    outer = IO + """
protected
  Buildings.Controls.OBC.CDL.Plant.Held h;
equation
  connect(u, h.u);
  connect(h.y, y);"""
    f = _facts(Held=held, Outer=outer)[CDL + "Plant.Outer"]
    assert (f.state, f.init, f.basis) == ("stateful", "readsInput", ["instance h"])


def test_complementary_conditional_instances_both_reading_the_input_read_input():
    # Wrong behavior caught: the comparators' pattern (greHys if have_hysteresis, greNoHys if not) read undecided, or
    # a single conditional path read as reading the input in every configuration.
    held = IO + "\ninitial equation\n  y = u;\nequation\n  when u > 1 then\n    y = u;\n  end when;"
    plain = IO + "\nequation\n  y = u;"
    both = IO + """
  parameter Boolean b = true;
protected
  Buildings.Controls.OBC.CDL.Plant.Held h if b;
  Buildings.Controls.OBC.CDL.Plant.Plain p if not b;
equation
  connect(u, h.u);
  connect(h.y, y);
  connect(u, p.u);
  connect(p.y, y);"""
    one = IO + """
  parameter Boolean b = true;
  parameter Real y_start = 0;
protected
  Buildings.Controls.OBC.CDL.Plant.Held h if b;
equation
  connect(u, h.u);
  connect(h.y, y);"""
    f = _facts(Held=held, Plain=plain, Both=both, One=one)
    assert (f[CDL + "Plant.Both"].state, f[CDL + "Plant.Both"].init) == ("stateful", "readsInput")
    assert f[CDL + "Plant.Both"].basis == ["instance h (conditional)"]
    assert (f[CDL + "Plant.One"].state, f[CDL + "Plant.One"].init) == ("stateful", "undecided")


def test_an_instance_of_a_class_outside_the_pins_is_undecided_not_guessed():
    # Wrong behavior caught: a class whose only possible state sits in an unread class (Reals.Sources.TimeTable's
    # Modelica.Blocks.Sources.CombiTimeTable) read stateless.
    body = IO + """
protected
  Modelica.Blocks.Continuous.FirstOrder f;
equation
  connect(u, f.u);
  connect(f.y, y);"""
    f = _facts(P=body)[CDL + "Plant.P"]
    assert f.state == "undecided" and f.init is None
    assert f.basis == ["unread: instance f is of Modelica.Blocks.Continuous.FirstOrder, which the pinned source does "
                       "not hold"]


def test_a_source_the_reader_cannot_parse_is_undecided_not_guessed():
    f = mo_state.facts({CDL + "Plant.P": "block P\n  Real x\nequation\nend P;\n"})[CDL + "Plant.P"]
    assert f.state == "undecided" and f.basis[0].startswith("unread: ")


# ---- packaging: no MBL source in any xetolib ----

OPEN = ("kw.cdl", "kw.cdl.g36.common", "kw.cdl.g36.ahu", "kw.cdl.g36.terminal")


def test_no_open_lib_directory_holds_mbl_source():
    # Wrong behavior caught: the .mo pins back inside a lib directory, where a 4.0.6 `xeto build` of the lib as it
    # stands zips them into the xetolib (measured: 132 .mo in kw.cdl.xetolib built in place).
    for lib in OPEN:
        assert list((LIBS / lib).rglob("*.mo")) == [], lib


def _fan():
    home = os.environ.get("FAN_HOME")
    if not home:
        return None
    f = pathlib.Path(home) / "bin" / ("fan.bat" if os.name == "nt" else "fan")
    return f if f.exists() else None


def _build(tmp):
    """Compile the four generated libs, as src/xeto holds them, in a new work dir whose fan.props path is FAN_HOME, so
    the home is only read. {lib: xetolib entry names}."""
    work = tmp / "build"
    (work / "src" / "xeto").mkdir(parents=True)
    (work / "fan.props").write_text("path=%s\n" % pathlib.Path(os.environ["FAN_HOME"]).as_posix(), encoding="utf-8")
    for lib in OPEN:
        shutil.copytree(LIBS / lib, work / "src" / "xeto" / lib)
    subprocess.run([str(_fan()), "xeto", "build"] + list(OPEN), cwd=str(work), capture_output=True)
    import zipfile
    out = {}
    for lib in OPEN:
        f = work / "lib" / "xeto" / (lib + ".xetolib")
        assert f.exists(), "no xetolib for %s: the xeto CLI can exit 0 when a lib fails" % lib
        out[lib] = zipfile.ZipFile(f).namelist()
    return out


def xetolib_extras(names):
    """The entries of a xetolib that are not a top-level .xeto, its NOTICE or its meta props: what a lib must not ship.
    MBL's licence asks for NOTICE, the compiler writes meta.props, and nothing else belongs in a generated xetolib."""
    return [n for n in names if "/" in n or not (n.endswith(".xeto") or n in ("NOTICE", "meta.props"))]


def test_a_xetolib_holds_only_xeto_its_notice_and_its_meta(tmp_path):
    # Wrong behavior caught: anything but the lib's Xeto shipping in the AFL-licensed xetolib: MBL's .mo, the
    # generator's inputs (CXF and json carrying MBL's HTML documentation), a stray file; or a xetolib without MBL's
    # NOTICE. Runs where FAN_HOME holds a Haxall toolchain, and skips elsewhere.
    if _fan() is None:
        pytest.skip("no Haxall toolchain in FAN_HOME; the packaging check runs where one is installed")
    for lib, names in _build(tmp_path).items():
        assert xetolib_extras(names) == [], (lib, xetolib_extras(names)[:5])
        assert "NOTICE" in names and "lib.xeto" in names, (lib, names)


def test_the_xetolib_content_check_refuses_what_it_should():
    assert xetolib_extras(["lib.xeto", "blocks.xeto", "NOTICE", "meta.props"]) == []
    assert xetolib_extras(["source/cxf/A.jsonld", "x.mo", "README.md", "sub/a.xeto", "build.props"]) == [
        "source/cxf/A.jsonld", "x.mo", "README.md", "sub/a.xeto", "build.props"]


# ---- the call vocabulary (an unclassified call is undecided, never pure) ----

# Every call the 132 pinned classes make, local functions included: 47 names at MBL 14.0.0.
CORPUS_CALLS = {
    "Buildings.Utilities.Math.Functions.round", "Buildings.Utilities.Psychrometrics.Functions.saturationPressure",
    "Modelica.Math.BooleanVectors.andTrue", "Modelica.Math.BooleanVectors.index", "Modelica.Math.Vectors.sort",
    "Modelica.Math.acos", "Modelica.Math.asin", "Modelica.Math.atan", "Modelica.Math.atan2", "Modelica.Math.cos",
    "Modelica.Math.exp", "Modelica.Math.log", "Modelica.Math.log10", "Modelica.Math.sin", "Modelica.Math.tan",
    "String", "abs", "assert", "ceil", "change", "computeSunRise", "computeSunSet", "delay", "der", "edge", "fill",
    "floor", "getIndex", "getInstanceName", "homotopy", "initial", "integer", "max", "min", "mod", "nextHourAngle",
    "noEvent", "ones", "pre", "reinit", "sample", "sin", "size", "smooth", "sqrt", "sum", "zeros"}
LOCAL_FUNCTIONS = {"computeSunRise", "computeSunSet", "getIndex", "nextHourAngle"}   # declared inside their classes


def test_the_classified_calls_are_exactly_the_corpus_calls(mbl_cdl):
    # Wrong behavior caught: a classified vocabulary wider than the corpus (a name no class uses, classified with
    # nothing to check it against) or narrower (a corpus call read as undecided), and a pin bump that brings a new call
    # in without someone classifying it. The four local functions are classified by their own declarations.
    assert mo_state.corpus_calls(mo_state.load(mbl_cdl)) == CORPUS_CALLS
    assert set(mo_state.CLASSIFIED_CALLS) == CORPUS_CALLS - LOCAL_FUNCTIONS
    assert set(mo_state.STATE_CALLS) | {"initial"} <= set(mo_state.CLASSIFIED_CALLS)


@pytest.mark.parametrize("call", ["previous(u)", "hold(u)", "spatialDistribution(u, 0, 1, true)",
                                  "Buildings.Utilities.Math.Functions.smoothMax(u, 0, 0.1)"])
def test_an_unclassified_call_reads_undecided_not_pure(call):
    # Wrong behavior caught: a state operator the reader does not know (Modelica 3.3's previous() and hold(),
    # spatialDistribution()) or a function outside the classified vocabulary read as a pure function, so a stateful
    # class reads stateless and a native binding skips the state gate.
    f = _facts(P=IO + "\nequation\n  y = " + call + ";")[CDL + "Plant.P"]
    name = call.split("(")[0]
    assert (f.state, f.init) == ("undecided", None), f
    assert f.basis == ["unread: a call to %s, which this reader has not classified" % name], f


def test_an_unclassified_call_in_a_stateful_class_leaves_its_init_undecided():
    # Wrong behavior caught: a stateful class whose initial outputs pass through an unknown call (previous(u) reads
    # the start value, not u) read as readsInput, which would pass the state gate on a guess.
    f = _facts(P=IO + "\nequation\n  when u > 1 then\n    y = previous(u);\n  end when;")[CDL + "Plant.P"]
    assert (f.state, f.init) == ("stateful", "undecided"), f


def test_a_local_function_is_classified_by_its_declaration():
    body = IO + """
protected
  function twice
    input Real x;
    output Real z;
  algorithm
    z := 2*x;
  end twice;
equation
  y = twice(u);"""
    assert _facts(P=body)[CDL + "Plant.P"].state == "stateless"
    impure = body.replace("  function twice", "  impure function twice")
    assert _facts(P=impure)[CDL + "Plant.P"].state == "undecided"


# ---- why a noInput class reads no input at the initial instant ----

@pytest.mark.parametrize("body,why", [
    ("  Buildings.Controls.OBC.CDL.Interfaces.RealOutput y;\n  parameter Real t0(fixed=false);\ninitial equation\n"
     "  t0 = time;\nequation\n  y = t0;", "noInputConnector"),
    (IO + "\n  Real x(start=0);\nequation\n  when sample(0, 1) then\n    x = u;\n  end when;\n  y = pre(x);",
     "preDelayed"),
    (IO + "\n  Buildings.Controls.OBC.CDL.Interfaces.BooleanInput b;\n  parameter Real y_start = 0;\ninitial equation\n"
     "  y = y_start;\nequation\n  when b then\n    y = u;\n  end when;", "parameterInit"),
])
def test_the_init_basis_names_why_no_input_is_read(body, why):
    # Wrong behavior caught: a source with no input, a pre() loop-breaker and a class whose inputs are read only after
    # the initial instant run together, though no initial output can read an input for the first two, and whether
    # one could is an open question for the third.
    f = _facts(P=body)[CDL + "Plant.P"]
    assert (f.state, f.init, f.init_basis) == ("stateful", "noInput", why), f


def test_an_output_read_directly_after_init_is_not_pre_delayed():
    # Wrong behavior caught: a class with one direct path to an input after the initial instant called a loop-breaker.
    body = IO + "\n  Real x(start=0);\n  Buildings.Controls.OBC.CDL.Interfaces.RealOutput z;\nequation\n" \
                "  when sample(0, 1) then\n    x = u;\n    z = u;\n  end when;\n  y = pre(x);"
    f = _facts(P=body)[CDL + "Plant.P"]
    assert (f.init, f.init_basis) == ("noInput", "parameterInit"), f


def test_a_noinput_class_with_no_basis_is_caught():
    planted = _replace_head(blocks_text(), "LogicalPre", ', cdlState:"stateful", cdlStateInit:"noInput", '
                                                         'cdlStateBasis:"pre"')
    assert any(b.startswith(CDL + "Logical.Pre: cdlStateInitBasis None") for b in fact_violations(planted))
