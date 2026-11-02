# Overview

These Xeto libraries model the Control Description Language (CDL) of ANSI/ASHRAE Standard 231-2026 and LBNL's Guideline 36 sample library, which writes the ASHRAE Guideline 36 sequences in CDL. They are for [Haxall](https://haxall.io/) and SkySpark, where CDL runs on the `hx.comps` component engine.

The specs are generated from the Modelica Buildings Library (MBL) 14.0.0, LBNL's reference implementation of CDL, read through modelica-json.

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

# Documentation

Browse the markdown documentation in this repo: [kw.cdl.doc](src/xeto/kw.cdl.doc/index.md).

# Validation

[validation/mbl-g36](validation/mbl-g36/README.md) replays MBL 14.0.0's air-side Guideline 36 controller validation models through the resolver and `hx.comps`, and compares every output with MBL's reference results. It downloads MBL at run time. No MBL results are kept in this repo.

# License

kW Engineering's work is licensed under the Academic Free License version 3.0 ([LICENSE](LICENSE)). Each library's `NOTICE` reproduces the MBL license, which covers the MBL names, defaults and descriptions the specs carry.
