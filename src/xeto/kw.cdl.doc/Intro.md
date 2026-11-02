<!--
title:      Intro
author:     Lincoln Harmer
created:    31 Oct 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

The Control Description Language (CDL) is the block language of ANSI/ASHRAE Standard 231-2026. Clause 7 of that standard defines 132 elementary blocks: logic, math, timers, sampling, routing, PID control and psychrometrics. A control sequence is a composite of those blocks, wired by connections. LBNL's Guideline 36 sample library writes the ASHRAE Guideline 36 sequences for air handlers and terminal units in CDL.

These libraries carry CDL and that sample library into Xeto, for the `hx.comps` component engine of Haxall and SkySpark.

Every CDL elementary block the libraries run is an `hx.comps` comp, a link, a small composite of comps, or an array class that expands onto comps. Five classes with no comp and no Guideline 36 use are refused by name. `kw.cdl` does not model the blocks a second time. It records, for each CDL class, which comp runs it and what CDL calls that comp's slots. A Guideline 36 sequence is a composite spec whose children are typed as those comps and wired on their slot names. The sequence's own parameters and connectors keep their CDL names, so it still reads in CDL terms from outside.

# Source

The specs are generated, not written by hand. The source is LBNL's Modelica Buildings Library (MBL), the reference implementation of CDL, read through modelica-json. CXF carries no MBL version, so the generator pins it and names it in every generated file header:

| Source | Version |
|-|-|
| Modelica Buildings Library | 14.0.0, commit `ad48324b74e9751e2e49dac5fe3c4dcb546755a2` |
| modelica-json | commit `5460add3b273286157412d8f5992493bd48ab061` |

Every generated spec names the MBL class it came from in `cdlClass`. Every elementary class also records its Clause 7 number.

ASHRAE 231 links the Guideline 36 sample library informatively (A2.1) and does not make it normative. The G36 specs are the sample library's types, not the text of Guideline 36.

# Libraries

| Library | Depends on | Content |
|-|-|-|
| `kw.cdl` | `sys`, `sys.comp`, `hx.comps` | One `CdlClass` instance per elementary class, naming the comp that runs it. The 28 array classes as abstract specs, four classes composed from comps, the classes refused by name, the four CDL enumerations, the block base, `CdlConstants` and the meta tags. See [Blocks](Blocks.md). |
| `kw.cdl.g36.common` | `sys`, `sys.comp`, `hx.comps`, `kw.cdl`, `ph`, `ph.points`, `ph.points.x` | The Generic, Types, ThermalZones, VentilationZones and ZoneGroups packages: 14 composites, 10 enumerations and 4 packages of constants. |
| `kw.cdl.g36.ahu` | as `kw.cdl.g36.common`, and `kw.cdl.g36.common` | The AHUs package (single-zone and multiple-zone VAV air handlers) and the FanCoilUnits package: 42 composites. |
| `kw.cdl.g36.terminal` | as `kw.cdl.g36.common`, and `kw.cdl.g36.common` | The TerminalUnits package, the controllers and subsequences of ten terminal unit families: 60 composites. |
| `kw.cdl.doc` | `sys` | This documentation. |

`kw.cdl.g36.ahu` and `kw.cdl.g36.terminal` each depend on `kw.cdl.g36.common`, and never on each other. FanCoilUnits sits in `kw.cdl.g36.ahu` because it instantiates `AHUs.SingleZone.VAV.SetPoints.ModeAndSetPoints`.

The libraries depend only on open platform libraries and Project Haystack's `ph` libraries. They name no other building ontology. No library is `hxSysOnly`, so a project can enable them.

# Requirements

The comps come from `hx.comps` with the additions of haxall pull requests #138 to #152. Those pull requests add most of the CDL blocks the stock engine lacked: hysteresis comparators, latches, edges, holds, counters and timers, sampled and triggered blocks, `loopCut` links with `UnitDelay`, continuous blocks, `CdlPid`, the CDL math and psychrometric blocks, and others.

The libraries need a Haxall and SkySpark release that carries those pull requests. They do not load on a release without them, and there is no shim for one.

# Status

Version 0.8.0, alpha, not released.

What is here:
- the four libraries, compiled against Haxall main with the hx.comps additions and Project Haystack's `ph` libraries;
- the resolver, `cdlResolve`, which turns one configured composite into a runnable comp graph. See [Resolver](Resolver.md);
- a validation of the resolved air-side Guideline 36 controllers against MBL's own validation results. See [Resolver](Resolver.md#validation);
- this documentation.

What is not here yet:
- **Binding.** No binder that matches connectors to a building's points is in this repo. See [Points](Points.md).
- **Layout.** The libraries do not carry CDL placement, so a block editor lays a sequence out on its own.
- **Plants.** The Guideline 36 Plants package is not generated.
