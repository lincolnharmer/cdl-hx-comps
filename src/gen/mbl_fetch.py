#!/usr/bin/env python3
"""MBL's .mo source for the state facts, fetched at its release tag and verified, never vendored. Nothing
MBL-authored is kept in the repo: the generator downloads MBL 14.0.0 at its release tag and verifies each file's
sha256, so regeneration stays reproducible.

  python -X utf8 src/gen/mbl_fetch.py              # download what the cache lacks, then verify every file
  python -X utf8 src/gen/mbl_fetch.py --check      # verify the cache and download nothing
  python -X utf8 src/gen/mbl_fetch.py --manifest <MBL checkout holding the tag>   # rewrite the manifest

--manifest reads the list of elementary classes from the generator's source directory (see cxf_source.py).

mbl_manifest.json holds the release (MBL's version, its tag, the commit the tag peels to, the repo) and, for each of
the 132 CDL elementary classes, the file's path in MBL's repo and its sha256 at the tag. The hashes are facts about
MBL's files, not MBL material. src/gen/stamp.json pins the same version and commit, and test_state.py holds the two
together.

The files go to a cache outside the repo: $KW_CDL_MBL_CACHE when set, else ~/.cache/kw-cdl/mbl, at
<cache>/<tag>/<path>. They are downloaded by the commit the tag peels to, which cannot move. Every file is checked
against its hash before it is written and again on every read. A file missing, a hash that differs, a .mo the
manifest does not list, or a download that fails or comes back short raises MblSourceError naming the file. A cached
file that no longer matches is downloaded again, and the run names it. Nothing falls back to another source.

generate.py reads the source through source_dir(): with fetch, so a regeneration downloads what it lacks; tests read
it with fetch=False through conftest.py, which skips a test loudly when no cache exists at all, naming the command
above, and fails it when a cache exists but does not verify.
"""
import hashlib
import http.client
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "mbl_manifest.json"
FETCH = "python -X utf8 src/gen/mbl_fetch.py"
CDL_DIR = "Buildings/Controls/OBC/CDL"
# By commit, not by tag: a tag can be moved, a commit cannot. The manifest pins the commit the tag peels to, and
# write_manifest refuses a tag that peels anywhere else.
RAW = "https://raw.githubusercontent.com/lbl-srg/modelica-buildings/{commit}/{path}"


class MblSourceError(Exception):
    """MBL's source is missing, differs from the manifest, or could not be fetched."""


class MblSourceAbsent(MblSourceError):
    """No cache of MBL's source exists at all: nothing has been fetched yet."""


def manifest(path=None):
    return json.loads(pathlib.Path(path or MANIFEST).read_text(encoding="utf-8"))


def cache_root():
    env = os.environ.get("KW_CDL_MBL_CACHE")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".cache" / "kw-cdl" / "mbl"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def problems(cache, man):
    """Every way `cache` (the <cache>/<tag> directory) differs from manifest `man`: a file missing, a hash that
    differs, or a .mo under the CDL directory the manifest does not list."""
    out = []
    for path, want in sorted(man["files"].items()):
        f = cache / path
        if not f.is_file():
            out.append("%s: missing" % path)
            continue
        got = sha256(f.read_bytes())
        if got != want:
            out.append("%s: sha256 %s, the manifest pins %s" % (path, got, want))
    listed = set(man["files"])
    for f in sorted((cache / CDL_DIR).rglob("*.mo")):
        rel = f.relative_to(cache).as_posix()
        if rel not in listed:
            out.append("%s: a .mo the manifest does not list" % rel)
    return out


def _download(url, opener=None):
    """The bytes at `url`. Three tries, then MblSourceError: a failed download is never read as an empty file. A body
    shorter than its Content-Length, or one the connection cut short (http.client.IncompleteRead, which is not an
    OSError), is a failed try, not a file."""
    opener = opener or urllib.request.urlopen
    err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kw-cdl-mbl-fetch"})
            with opener(req, timeout=60) as r:
                data = r.read()
                want = r.headers.get("Content-Length") if getattr(r, "headers", None) is not None else None
            if want is not None and int(want) != len(data):
                raise http.client.IncompleteRead(data, int(want) - len(data))
            return data
        except (OSError, http.client.HTTPException) as e:
            err = e
            time.sleep(2 * (attempt + 1))
    raise MblSourceError("could not download %s after 3 tries: %r" % (url, err))


def fetch(cache=None, man=None, download=None):
    """Download into `cache` (default cache_root()/<tag>) every manifest file it lacks or holds with a wrong hash,
    each verified before it is written, then verify the whole cache. Returns the <cache>/<tag> directory."""
    man = man or manifest()
    cache = pathlib.Path(cache) if cache else cache_root() / man["tag"]
    download = download or _download
    got, replaced = 0, []
    for path, want in sorted(man["files"].items()):
        f = cache / path
        if f.is_file():
            have = sha256(f.read_bytes())
            if have == want:
                continue
            # Say so: a cached file that no longer matches was edited or corrupted, and a silent repair hides that.
            replaced.append(path)
            print("mbl_fetch: %s in the cache has sha256 %s, the manifest pins %s; downloading it again"
                  % (path, have, want), file=sys.stderr)
        data = download(RAW.format(commit=man["commit"], path=path))
        if sha256(data) != want:
            raise MblSourceError("%s at %s has sha256 %s; the manifest pins %s. Nothing was written."
                                 % (path, man["tag"], sha256(data), want))
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, f)
        got += 1
    bad = problems(cache, man)
    if bad:
        raise MblSourceError("MBL %s in %s does not verify:\n  %s" % (man["tag"], cache, "\n  ".join(bad)))
    print("MBL %s: %d files verified in %s (%d downloaded, %d of them replacing a cached file that did not match: %s)"
          % (man["tag"], len(man["files"]), cache, got, len(replaced), ", ".join(replaced) or "none"))
    return cache


def source_dir(fetch_missing=True, cache=None, man=None):
    """The verified CDL directory of MBL's source, for mo_state.load. With `fetch_missing`, download what the cache
    lacks first. Without it, raise MblSourceAbsent when no file of the cache exists, and MblSourceError when the cache
    exists but does not verify."""
    man = man or manifest()
    cache = pathlib.Path(cache) if cache else cache_root() / man["tag"]
    if fetch_missing:
        return fetch(cache, man) / CDL_DIR
    cdl = cache / CDL_DIR
    if not cdl.is_dir() or not any(cdl.rglob("*.mo")):
        raise MblSourceAbsent("no MBL %s source in %s; run: %s" % (man["tag"], cache, FETCH))
    bad = problems(cache, man)
    if bad:
        raise MblSourceError("MBL %s in %s does not verify (rerun %s):\n  %s"
                             % (man["tag"], cache, FETCH, "\n  ".join(bad)))
    return cache / CDL_DIR


def write_manifest(mbl_dir, src=None):
    """Rewrite the manifest from an MBL checkout holding the tag stamp.json's version names: the tag must peel to the
    stamp's commit, and each file is read from git at that commit (so LF, whatever the checkout's autocrlf). The paths
    are the elementary classes CXF-Core lists, read from the generator's source directory `src` (by default
    cxf_source.source_root())."""
    import cxf_source
    src = pathlib.Path(src) if src else cxf_source.source_root()
    stamp = json.loads((HERE / "stamp.json").read_text(encoding="utf-8"))
    tag, commit = "v" + stamp["mbl"], stamp["mblCommit"]

    def git(*args):
        return subprocess.run(["git", "-C", str(mbl_dir)] + list(args), capture_output=True, check=True).stdout
    peeled = git("rev-parse", "refs/tags/%s^{commit}" % tag).decode().strip()
    if peeled != commit:
        raise MblSourceError("tag %s peels to %s in %s; stamp.json pins %s" % (tag, peeled, mbl_dir, commit))
    doc = json.loads((src / "kw.cdl/cdl-elementary.jsonld").read_text(encoding="utf-8"))
    prefix = "S231:Buildings.Controls.OBC.CDL."
    rels = sorted(n["@id"][len(prefix):].replace(".", "/") for n in doc["@graph"]
                  if n.get("@type") == "S231:ElementaryBlock" and n["@id"].startswith(prefix))
    files = {}
    for rel in rels:
        path = "%s/%s.mo" % (CDL_DIR, rel)
        files[path] = sha256(git("show", "%s:%s" % (commit, path)))
    out = {"mbl": stamp["mbl"], "tag": tag, "commit": commit, "repo": "https://github.com/lbl-srg/modelica-buildings",
           "note": "The sha256 of each CDL elementary class's .mo in the Modelica Buildings Library at this tag, as git "
                   "stores it (LF). Facts about MBL's files, not MBL material: the files are fetched at generate by "
                   "src/gen/mbl_fetch.py and verified against these hashes.",
           "files": files}
    MANIFEST.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("wrote %d hashes for MBL %s (%s)" % (len(files), tag, commit[:8]))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["--manifest"] and len(args) == 2:
            write_manifest(args[1])
        elif args == ["--check"]:
            print("MBL %s verified in %s" % (manifest()["tag"], source_dir(fetch_missing=False).parents[3]))
        elif not args:
            fetch()
        else:
            sys.exit("usage: mbl_fetch.py [--check | --manifest <MBL checkout>]")
    except MblSourceError as e:
        print("mbl_fetch: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
