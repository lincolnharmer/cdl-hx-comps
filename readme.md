# Overview

These Xeto libraries model the Control Description Language (CDL) of ANSI/ASHRAE Standard 231-2026 and LBNL's Guideline 36 sample library, which writes the ASHRAE Guideline 36 sequences in CDL. They are for [Haxall](https://haxall.io/) and SkySpark, where CDL runs on the `hx.comps` component engine.

The specs are generated from the Modelica Buildings Library (MBL) 14.0.0, LBNL's reference implementation of CDL, read through modelica-json. The generator is in this repo, under `src/gen`. See [Regenerating](#regenerating).

# Libraries

| Library | Depends on | Content |
|-|-|-|
| `kw.cdl` | `sys`, `sys.comp`, `hx.comps` | The CDL elementary classes, each mapped to the `hx.comps` comp that runs it, plus the array classes, enumerations and meta tags |
| `kw.cdl.g36.common` | `sys`, `sys.comp`, `hx.comps`, `kw.cdl`, `ph`, `ph.points`, `ph.points.x` | Shared Guideline 36 types, constants and composites |
| `kw.cdl.g36.ahu` | as `kw.cdl.g36.common`, and `kw.cdl.g36.common` | Guideline 36 air handler and fan coil sequences |
| `kw.cdl.g36.terminal` | as `kw.cdl.g36.common`, and `kw.cdl.g36.common` | Guideline 36 terminal unit sequences |
| `kw.cdl.doc` | `sys` | Documentation |
| `kw.cdl.resolve` | `sys`, `axon`, `hx` | The Axon function `cdlResolve`, bound to the `cdlResolve` pod |

The Fantom pod `cdlResolve` (`src/fan/cdlResolve`) is the resolver. It turns one configured Guideline 36 sequence and its parameter values into a single flat graph of `hx.comps` comps that runs as is. See [Resolver](src/xeto/kw.cdl.doc/Resolver.md).

# Model

Every CDL elementary block the libraries run is an `hx.comps` comp, a link, a small composite of comps, or an array class that expands onto comps. Five classes with no comp and no Guideline 36 use are refused by name. `kw.cdl` holds one `CdlClass` instance per class, recording which comp runs it and what CDL calls the comp's slots. A Guideline 36 sequence is a composite whose children are typed as those comps and linked on their slot names, while its own parameters and connectors keep their CDL names. Each connector that reads or writes a building point names its Project Haystack point spec. A composite still carries CDL expressions, conditions and array sizes, which resolve when a sequence is instantiated for one piece of equipment.


# Requirements

The libraries and the resolver need a Haxall release that carries the `hx.comps` additions of haxall pull requests #138 to #152. Those pull requests are based on haxall main, and they rely on `hx.comps` changes made on main after the v4.0.7 release, so Haxall v4.0.7 alone is not enough. The same holds for a SkySpark release, which ships Haxall's pods. Everything here is version 0.8.0, alpha, and not released.

# Building

Everything builds with Haxall's own tools. No SkySpark install is needed.

- The libraries: from a Haxall environment whose path includes this repo's `src/xeto`, run `fan xeto build kw.cdl kw.cdl.g36.common kw.cdl.g36.ahu kw.cdl.g36.terminal kw.cdl.resolve kw.cdl.doc`.
- The resolver: `fan src/fan/cdlResolve/build.fan`, in the same environment.
- The tests: `fant cdlResolve`. The dependency guard test reads the sources from the path in the environment variable `CDL_RESOLVE_SRC`, set to this repo's `src` directory.

# Regenerating

The generator in `src/gen` rebuilds the four generated libraries (`kw.cdl`, `kw.cdl.g36.common`, `kw.cdl.g36.ahu`, `kw.cdl.g36.terminal`) from MBL 14.0.0. It is Python with no packages beyond the standard library; the tests need pytest. Run on the pinned versions, it writes `src/xeto/kw.cdl*/` byte for byte as committed.

The repo keeps no MBL source and no modelica-json output. The generator's inputs are rebuilt on each machine:
- `regen_cxf.sh` runs modelica-json over MBL and writes its output into a source directory outside the repo, `~/.cache/kw-cdl/source` unless `KW_CDL_SOURCE` names another. It then checks every file against `src/gen/source_manifest.json`. A file missing, differing or unlisted stops it, naming the file. `generate.py` makes the same check before it reads anything.
- `generate.py` downloads the 132 CDL `.mo` files it reads from MBL's repository at the release commit, into `~/.cache/kw-cdl/mbl` unless `KW_CDL_MBL_CACHE` names another, and checks each one against `src/gen/mbl_manifest.json`.

Prerequisites:
- Python 3.12 or later, and pytest 9 for the tests.
- Node.js with npm, for modelica-json.
- git and bash (Git Bash on Windows).
- A clone of [modelica-buildings](https://github.com/lbl-srg/modelica-buildings) at tag `v14.0.0`, commit `ad48324b74e9751e2e49dac5fe3c4dcb546755a2`.
- A clone of [modelica-json](https://github.com/lbl-srg/modelica-json) at commit `5460add3b273286157412d8f5992493bd48ab061`. `regen_cxf.sh` copies `src/gen/package-lock.json` into it and runs `npm ci` there, which replaces its `node_modules`.
- Network access to github.com for the `.mo` download.

From the repo root, in bash:

```
git clone https://github.com/lbl-srg/modelica-buildings ../mbl
git -C ../mbl checkout ad48324b74e9751e2e49dac5fe3c4dcb546755a2
git clone https://github.com/lbl-srg/modelica-json ../modelica-json
git -C ../modelica-json checkout 5460add3b273286157412d8f5992493bd48ab061

MBL_DIR=$PWD/../mbl MJ_DIR=$PWD/../modelica-json bash src/gen/regen_cxf.sh   # rebuild and check the inputs
python -X utf8 src/gen/generate.py                                             # write the libraries and reports
git status --short src                                                         # a regeneration changes nothing
python -X utf8 src/gen/check_open_libs.py                                      # depends, notices, names
MBL_DIR=$PWD/../mbl python -X utf8 -m pytest src/gen -q -p no:cacheprovider    # the generator's tests
```

On Windows, give `KW_CDL_SOURCE` and `KW_CDL_MBL_CACHE` as Windows paths if you set them. The test session stops before running any test when the source directory, the `.mo` cache or `MBL_DIR` is missing or does not verify. A few tests run only where `FAN_HOME` holds a Haxall toolchain, `HX_COMPS_SRC` names the `hx.comps` Xeto source, or `HAYSTACK_XETO_SRC` names a Project Haystack xeto checkout's `src/xeto`; they skip elsewhere.

# Documentation

Browse the markdown documentation in this repo: [kw.cdl.doc](src/xeto/kw.cdl.doc/index.md).

# License

kW Engineering's work is licensed under the Academic Free License version 3.0 ([LICENSE](LICENSE)). Each library's `NOTICE` reproduces the MBL license, which covers the MBL names, defaults and descriptions the specs carry.
