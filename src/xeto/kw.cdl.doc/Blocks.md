<!--
title:      Blocks
author:     Lincoln Harmer
created:    31 Oct 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

`kw.cdl` covers all 132 elementary classes of Clause 7. Each one lands in exactly one of these forms:

| Form | Classes | Where |
|-|-|-|
| A `CdlClass` instance naming one `hx.comps` comp | 93 | `classes.xeto` |
| A `CdlClass` instance naming a link with no comp | 2 | `classes.xeto` |
| An array class, an abstract spec marked `cdlExpand` | 28 | `blocks.xeto`, with a `CdlClass` instance in `classes.xeto` |
| A small composite of comps | 4 | `blocks.xeto`, with a `CdlClass` instance in `classes.xeto` |
| Refused by name | 5 | `@cdl-refused` in `classes.xeto` |

That is 127 `CdlClass` instances and 5 refusals. A class's `kw.cdl` name is its MBL package and class joined, with acronyms case-folded: `Buildings.Controls.OBC.CDL.Reals.Limiter` is `RealsLimiter`, and `Reals.PIDWithReset` is `RealsPidWithReset`. Its `CdlClass` instance is `@cdl-` and that name, such as `@cdl-RealsLimiter`. Only the array and composed classes also have a spec of that name.

The four CDL enumerations are `TypesExtrapolation`, `TypesSimpleController`, `TypesSmoothness` and `TypesZeroTime`.

# CdlClass

One `CdlClass` instance records how one CDL class runs. A composite's child is typed as the comp itself, or as the `kw.cdl` spec of an array, composed or link class, and its `cdlOf` meta names the instance. CXF import and export, and a conformance report, read the CDL class and its CDL names back from it.

```
@cdl-RealsLimiter: CdlClass {
  cdlClass: "Buildings.Controls.OBC.CDL.Reals.Limiter"
  grade: "nativeParams"
  clause: "7.5.67.1"
  comp: hx.comps::Limiter
  connectors: {u:"in", y:"out"}
  params: {uMax:"uMax", uMin:"uMin"}
  departures: {"Equal limits give that value. MBL rejects them.", "Limits convert to the unit of `in`, an offset included, so a °C limit fits a °F `in`.", ...}
  unitRule: {family:"A", keep:"u,uMin,uMax,y"}
  state: "stateless"
}
```

The dict keys are CDL names with the first letter lowered. `cdlNames` restores the exact spelling where the two differ, such as `{td:"Td", ti:"Ti"}` on the PID classes.

| Field | Holds |
|-|-|
| `cdlClass` | The MBL class path |
| `grade` | How the class runs, a `CdlGrade` (below) |
| `clause`, `name231` | The Clause 7 number, and Clause 7's spelling where it differs from MBL's |
| `comp` | The `hx.comps` comp, or the `kw.cdl` spec of a composite or array class |
| `connectors` | CDL connector to comp slot |
| `params` | CDL parameter to the comp slot it is set on |
| `feeds` | CDL name to `{slot, via}`: the slot is linked from a comp of spec `via` the generator adds beside the child |
| `convert` | CDL parameter to its conversion: `sec` (Real seconds to a Duration), `int`, `float`, or `enum` with each CDL key mapped to the comp's key |
| `fixed` | Comp slot to the value it always takes |
| `cdlDefaults` | CDL parameter to the CDL default written when an instance leaves it unbound |
| `linkAlways` | CDL input to the constant linked into it where CDL leaves it unconnected |
| `loopCut` | CDL inputs whose incoming link carries `loopCut` |
| `whenNull` | CDL input to the `whenNull` of the feed that carries it |
| `writeWhenUnit` | CDL parameters written whenever their unit group carries a unit (a PID's `r`). See [Units](Units.md). |
| `compoundGain` | The comp an instance runs on when its gain has a unit the unit database lacks. See [Units](Units.md). |
| `linkFrom`, `linkTo` | For a link class: the input the wire starts at, and the output it replaces |
| `departures` | Each way the comp differs from MBL that a sequence can see |
| `unitRule` | How the class carries units, for unit propagation. See [Units](Units.md). |
| `bounds` | CDL parameter or connector to the bounds its declaration gives it, with the meta that says where each came from |
| `state`, `stateInit`, `stateInitBasis`, `stateBasis` | The state facts, as the `cdlState` meta tags describe in [Meta](Meta.md) |

## Grades

| Grade | Classes | Meaning |
|-|-|-|
| `native` | 44 | One comp, the connectors renamed |
| `nativeParams` | 46 | One comp, with parameters set on its slots or fed by a linked comp |
| `const` | 3 | A constant comp whose output the parameter sets |
| `link` | 2 | A wire from one connector to the other, with no comp |
| `composite` | 4 | A `kw.cdl` composite of comps |
| `array` | 28 | An abstract `kw.cdl` spec that expands when a sequence is instantiated |

One comp can run several classes. `hx.comps::NumberSwitch` runs Reals.Switch, Integers.Switch, BooleanToReal and BooleanToInteger, each with its own instance.

## Parameters and feeds

A CDL parameter reaches its comp in one of three ways:
- **On a slot.** `params` names the comp slot, and the value is written there, converted by `convert`.
- **Through a feed.** `feeds` names the slot and the spec of a comp linked into it. A `NumberConst` feed supplies a parameter's value.
- **As a signal.** A CDL input that the comp holds as a plain `Number` or `Bool` slot, not a status type, is carried by a `StatusNumberToNumber` or `StatusBoolToBool` feed.

In a composite, the generator adds each feed beside the child it supplies and marks it `cdlFeed`. See [Sequences](Sequences.md).

```
@cdl-ConversionsBooleanToInteger: CdlClass {
  cdlClass: "Buildings.Controls.OBC.CDL.Conversions.BooleanToInteger"
  grade: "nativeParams"
  clause: "7.5.72.1"
  comp: hx.comps::NumberSwitch
  connectors: {u:"inSwitch", y:"out"}
  feeds: {integerFalse:{slot:"inFalse", via:hx.comps::NumberConst}, integerTrue:{slot:"inTrue", via:hx.comps::NumberConst}}
  cdlDefaults: {integerFalse:"0", integerTrue:"1"}
  ...
}
```

A timer converts its CDL seconds to a Duration and fixes a slot CDL does not have:

```
@cdl-LogicalTrueDelay: CdlClass {
  cdlClass: "Buildings.Controls.OBC.CDL.Logical.TrueDelay"
  grade: "nativeParams"
  clause: "7.5.78.1"
  comp: hx.comps::BoolDelay
  connectors: {u:"in", y:"out"}
  params: {delayOnInit:"delayOnInit", delayTime:"onDelay"}
  convert: {delayTime:"sec"}
  fixed: {offDelay:0sec}
  ...
}
```

## Departures

`departures` lists, in plain sentences, each way the comp's behaviour differs from MBL's that a sequence can see. One applies to every `native` and `nativeParams` class: CDL values are never null and carry no status, while every `hx.comps` comp has its own null and status rule. The three `const` classes carry no departures. A sequence sees that difference only when an input point is null, stale or faulted. Others are specific, for example from `@cdl-LogicalTimer`:

> At start-up with `t` <= 0, MBL starts `passed` true while `u` is false. The comp starts `passed` false, so the two differ until `u` first turns true.

# Links: IntegerToReal and Pre

Two classes compile to a link with no comp.

- **`Conversions.IntegerToReal`.** CDL Integer and Real both ride `hx.comps::StatusNumber`, so the wire carries the value unchanged.
- **`Logical.Pre`.** The class reads the previous value of its input, MBL's way of breaking an algebraic loop. It becomes a `loopCut` link, which delivers the previous cycle's value at the end of the execute cycle.

```
@cdl-LogicalPre: CdlClass {
  cdlClass: "Buildings.Controls.OBC.CDL.Logical.Pre"
  grade: "link"
  clause: "7.5.69.1"
  loopCut: "u"
  linkFrom: "u"
  linkTo: "y"
  departures: {"The link reads null on the first cycle where MBL reads `pre_u_start`. From the second cycle on it reads the previous cycle value of `u`, as MBL.", ...}
  ...
}
```

In a composite, the CDL instance stays as a record typed `kw.cdl::CdlWire`, so its name and bindings survive a round trip to CXF. The link that replaces it runs from the instance's source to its target and names it in `cdlLinkVia`. From `kw.cdl.g36.common::GenericTimeSuppression`:

```
lat: hx.comps::SetResetLatch? <cdlInstance, cdlName:"lat", cdlOf:@kw.cdl::cdl-LogicalLatch> {
  inClear: <link:"pasSup.out", loopCut, cdlLinkVia:"pre1">
  in: <link:"greThr.out">
}
...
pre1: kw.cdl::CdlWire? <cdlInstance, cdlName:"pre1", cdlOf:@kw.cdl::cdl-LogicalPre>
```

A Pre's `pre_u_start` stays on its record as a binding where MBL sets one (`cdlBind:{pre_u_start:"true"}`). The resolver writes it as the starting value of the target slot. See [Resolver](Resolver.md).

`Discrete.UnitDelay` also cuts a loop. It runs on `hx.comps::UnitDelay`, and its `loopCut: "u"` marks its incoming link `loopCut`.

# Array classes

28 classes have a connector or parameter sized as an array. `sys.comp` has no array slots, so these stay as abstract specs in `blocks.xeto`, marked `cdlExpand`. They expand onto existing comps when a sequence is instantiated for a building and every size is known.

| Group | Classes |
|-|-|
| Reductions | Reals and Integers `MultiSum`, Reals `MultiMax` and `MultiMin`, Logical `MultiAnd` and `MultiOr` |
| Matrix | `MatrixGain`, `MatrixMax`, `MatrixMin` |
| Routing | `ScalarReplicator`, `VectorReplicator`, `VectorFilter`, `Extractor` and `ExtractSignal`, each in Real, Integer and Boolean |
| No comp | Reals `Sort`, and the Reals, Integers and Logical `Sources.TimeTable` |

```
RealsMultiSum: CdlBlock <cdlClass:"Buildings.Controls.OBC.CDL.Reals.MultiSum", abstract, cdlExpand, cdlElementary, cdlClause:"7.5.29.1", cdl231Name:"CDL.Reals.Multisum", cdlState:"stateless"> {
  // Input gains
  k: List? <cdlParam, cdlName:"k", cdlType:"Real", cdlArraySize:"(nin)", cdlDefault:"fill(1,nin)">
  // Number of input signals
  nin: Int? <cdlParam, cdlName:"nin", cdlType:"Integer", minVal:"0"> "0"
  // Input to multiplied by gain and then added
  u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(nin)">
  // Sum of inputs times gains
  y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly>
}
```

The array classes keep their state facts as meta on the spec. Their `CdlClass` instance names the spec as `comp`, with grade `array`.

hx.comps has no comp for `Sort` or the three `TimeTable` classes. No Guideline 36 sequence outside Plants uses them.

# Composed classes

Four classes run on two comps, so `kw.cdl` writes each as a small composite: `LogicalNand`, `LogicalNor`, `RealsSourcesPulse` and `IntegersSourcesPulse`.

```
LogicalNand: CdlBlock <cdlClass:"Buildings.Controls.OBC.CDL.Logical.Nand"> {
  // Input signal for 'nand'
  u1: hx.comps::StatusBool? <cdlInput, cdlName:"u1", cdlType:"Boolean">
  // Input signal for 'nand'
  u2: hx.comps::StatusBool? <cdlInput, cdlName:"u2", cdlType:"Boolean">
  // Output with false if both inputs are true
  y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"not1.out">
  and1: hx.comps::And? <cdlInstance, cdlName:"and1", cdlOf:@kw.cdl::cdl-LogicalAnd> {
    inA: <link:"u1">
    inB: <link:"u2">
  }
  not1: hx.comps::Not? <cdlInstance, cdlName:"not1", cdlOf:@kw.cdl::cdl-LogicalNot> {
    in: <link:"and1.out">
  }
}
```

The two pulse sources run a `BoolPulse` into a `NumberSwitch`, with `offset` and `offset+amplitude` fed into the switch's two inputs.

# Refused classes

Five classes have no comp and no composition, and no Guideline 36 sequence uses them. `@cdl-refused` lists each one with its reason and its state facts:

| Class | Reason |
|-|-|
| `Reals.Sources.CalendarTime` | No comp outputs year, month, day, hour, minute and weekday as numbers |
| `Reals.Sources.CivilTime` | No comp outputs time as seconds |
| `Reals.Sources.Ramp` | CDL Ramp is one-shot: `offset` before `startTime`, then a rise of `height` over `duration` |
| `Reals.Sources.Sin` | SineWave has no `phase` or `startTime`, measures `amplitude` peak to peak, takes a `period` of at least 1sec, and is phased from its own start |
| `Utilities.SunRiseSet` | No comp computes sunrise or sunset times |

A tool that meets one of these classes refuses it by name.

# CdlBlock

Every generated composite and array class subtypes `CdlBlock`, a plain `sys.comp::Comp` with no runtime slot:

```
CdlBlock: sys.comp::Comp <abstract> {
  cdlBlock
  cdlPath: Str?
  cdlLayer: Str?
  cdlCites: Dict?
}
```

- `cdlPath`: the block's instance path in a design, such as `seq.supTem`.
- `cdlLayer`: which class of the design the block came from, `intent` or `plant`.
- `cdlCites`: per parameter, where its value came from. `design` means a CDL modifier, and `referenceDefault` means MBL's default.

# Constant packages

Modelica lets a package hold constants that are neither a block nor an enumeration. Each such package becomes one instance of `CdlConstants`, and a dotted name in an expression resolves through these instances. `kw.cdl.g36.common` holds four: `typesDemandLimitLevels`, `typesFreezeProtectionStages`, `typesOperationModes` and `typesZoneStates`.

```
@typesOperationModes: kw.cdl::CdlConstants {
  cdlClass: "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes"
  cdlType: "Integer"
  cdlConstants: {
    coolDown: Number "2"
    freezeProtection: Number "6"
    occupied: Number "1"
    setBack: Number "5"
    setUp: Number "3"
    unoccupied: Number "7"
    warmUp: Number "4"
  }
}
```

A generated literal that came from one of these constants names it in `cdlLiteralExprs`, for example `{out:"Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.occupied"}`.
