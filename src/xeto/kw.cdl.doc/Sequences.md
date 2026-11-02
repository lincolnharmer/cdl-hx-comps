<!--
title:      Sequences
author:     Lincoln Harmer
created:    31 Oct 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

The Guideline 36 sequences are CDL composites. Each MBL composite under `Buildings.Controls.OBC.ASHRAE.G36`, outside Plants, becomes one spec that subtypes `kw.cdl::CdlBlock`. Its name joins the MBL package path and class, with acronyms case-folded, so `TerminalUnits.CoolingOnly.Controller` is `TerminalUnitsCoolingOnlyController` and `AHUs.MultiZone.VAV.Controller` is `AhusMultiZoneVavController`.

| Library | Composites | Also holds |
|-|-|-|
| `kw.cdl.g36.common` | 14 | 10 enumerations, 4 constant packages |
| `kw.cdl.g36.ahu` | 42 | |
| `kw.cdl.g36.terminal` | 60 | |

# A composite

A composite has these kinds of slot:
- **Parameters**, marked `cdlParam`. They are plain `Number`, `Bool`, `Int`, `List` or enumeration slots carrying MBL's default.
- **Connectors**, marked `cdlInput` or `cdlOutput`. A scalar connector rides an `hx.comps` status type, `StatusNumber` or `StatusBool`. A vector connector is a `List`. Each keeps its CDL name in `cdlName`.
- **Children**, marked `cdlInstance`. An elementary child is typed as the `hx.comps` comp that runs it, or as the `kw.cdl` spec of an array, composed or link class, and `cdlOf` names its `CdlClass` instance. A composite child is typed as its G36 spec and has no `cdlOf`.
- **Feeds**, marked `cdlFeed`. These are comps the generator adds beside a child to supply a parameter or carry a signal.

Links are `sys.comp` `link` meta on a child's sink slots. On a comp child, sink and source are `hx.comps` slot names (`inA`, `inB`, `out`), not CDL names. On a composite child they are the child's connectors in Xeto slot names, and a source may be one of the composite's own connectors, such as `tSet`.

An abridged example from `kw.cdl.g36.common`, `GenericTimeSuppression`:

```
GenericTimeSuppression: kw.cdl::CdlBlock <cdlClass:"Buildings.Controls.OBC.ASHRAE.G36.Generic.TimeSuppression"> {
  // Gain factor to calculate suppression time based on the change of the setpoint, seconds per Kelvin. ...
  chaRat: Number? <cdlParam, cdlName:"chaRat", cdlType:"Real", cdlUnit:"s/K", cdlValueInReference:"true"> "540"
  // Near zero temperature difference, below which the difference will be seen as zero
  dTHys: Number? <cdlParam, cdlName:"dTHys", cdlType:"Real", cdlUnit:"K", cdlQuantityKind:"TemperatureDifference", cdlDelta, cdlTab:"Advanced", cdlValueInReference:"false"> "0.25"
  // Maximum suppression time. ...
  maxTim: Number? <cdlParam, cdlName:"maxTim", cdlType:"Real", cdlUnit:"s", cdlQuantityKind:"Time", quantity:"time", unit:"sec", cdlValueInReference:"true"> "1800"
  // Zone temperature
  tZon: hx.comps::StatusNumber? <cdlInput, cdlName:"TZon", cdlType:"Real", cdlUnit:"K", cdlQuantityKind:"ThermodynamicTemperature", quantity:"temperature", cdlPointSpec:ph.points::ZoneAirTempSensor, cdlPointScope:"zone">
  // True when there is no setpoint change, or suppression time has passed after setpoint change
  yAftSup: hx.comps::StatusBool? <cdlOutput, cdlName:"yAftSup", cdlType:"Boolean", transient, readonly, link:"pasSupTim.out">
  // Check if there is setpoint change
  greThr: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"greThr", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold, cdlBind:{h:"0.5*dTHys", t:"dTHys"}, cdlFinalBind:"h,t"> {
    inB: <link:"greThr_t.out">
    inA: <link:"abs1.out">
  }
  // Maximum suppression time
  maxSupTim: hx.comps::NumberConst? <cdlInstance, cdlName:"maxSupTim", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"maxTim"}, cdlFinalBind:"k">
  // Ignore the first sampling period
  truDel: hx.comps::BoolDelay? <cdlInstance, cdlName:"truDel", cdlOf:@kw.cdl::cdl-LogicalTrueDelay, cdlBind:{delayTime:"samplePeriod"}, cdlFinalBind:"delayOnInit,delayTime"> {
    delayOnInit: "true"
    offDelay: 0sec
    in: <link:"con1.out">
  }
  // Delay value to record input value
  uniDel: hx.comps::UnitDelay? <cdlInstance, cdlName:"uniDel", cdlOf:@kw.cdl::cdl-DiscreteUnitDelay, cdlBind:{samplePeriod:"samplePeriod"}, cdlFinalBind:"samplePeriod"> {
    in: <link:"samSet.out", loopCut>
  }
  greThr_t: hx.comps::NumberConst? <cdlFeed:"greThr.t">
}
```

Reading it:
- `greThr` runs CDL `Reals.GreaterThreshold` on `hx.comps::GreaterThanHys`. Its CDL input `u` is the comp's `inA`.
- `greThr`'s threshold `t` is bound to the expression `dTHys`. The class feeds `t` into the comp's `inB`, so the generator adds the feed `greThr_t`, a `NumberConst`, and links it. The resolver writes the bound value on the feed.
- `maxSupTim` is a constant comp. Its `k` is bound to the parameter `maxTim`, and MBL marks that binding final.
- `truDel` carries literals on its comp slots. `delayOnInit` is a binding MBL writes as a literal. `offDelay: 0sec` is a value the class always fixes.
- `uniDel`'s input link carries `loopCut`, because `Discrete.UnitDelay` cuts a loop.
- The composite's own output `yAftSup` links to the `out` slot of the `pasSupTim` child.

# Bindings

A child's CDL bindings take one of two forms:
- **A literal** is written as the comp slot's value, with its SI unit in `cdlLiteralUnits` (see [Units](Units.md)).
- **An expression** in the composite's parameters stays in `cdlBind`, keyed by CDL parameter with its first letter lowered. It resolves when the sequence is instantiated.

Where an instance leaves a parameter unbound, the generator writes the CDL default and names the parameter in `cdlDefaulted`. A composite child takes its bindings in `cdlBind` too:

```
conLoo: kw.cdl.g36.common::ThermalZonesControlLoops? <cdlInstance, cdlName:"conLoo", cdlBind:{tiCooCon:"TiCooCon", tiHeaCon:"TiHeaCon", dTHys:"dTHys", kCooCon:"kCooCon", kHeaCon:"kHeaCon", looHys:"looHys", timChe:"timChe"}, ...>
```

# Conditions and alternative links

A conditional child or connector carries its guard in `cdlCondition`, as a CDL expression of the composite's parameters. Where a sink is driven by one of several conditional sources, its link is `cdlAltLink`. In a valid configuration exactly one of the sources is present. From `TerminalUnitsCoolingOnlyController`, abridged:

```
minFlo: kw.cdl.g36.common::VentilationZonesTitle24Setpoints? <cdlInstance, cdlName:"minFlo", ..., cdlCondition:"venStd == Buildings.Controls.OBC.ASHRAE.G36.Types.VentilationStandard.California_Title_24">
setPoi: kw.cdl.g36.common::VentilationZonesAshrae62_1Setpoints? <cdlInstance, cdlName:"setPoi", ..., cdlCondition:"venStd == Buildings.Controls.OBC.ASHRAE.G36.Types.VentilationStandard.ASHRAE62_1">
actAirSet: kw.cdl.g36.terminal::TerminalUnitsCoolingOnlySubsequencesActiveAirFlow? <cdlInstance, cdlName:"actAirSet", cdlBind:{vCooMax_flow:"VCooMax_flow"}, cdlFinalBind:"vCooMax_flow"> {
  vOccMin_flow: <cdlAltLink:"minFlo.vOccZonMin_flow,setPoi.vOccZonMin_flow">
  uOpeMod: <link:"uOpeMod">
}
```

`venStd` picks one ventilation standard, so exactly one of `minFlo` and `setPoi` is present, and `actAirSet.vOccMin_flow` reads from that one.

# Arrays and expansion

Seven composites carry `cdlExpand`. Each holds a vector connector, a vectorized child or an array class child, and its sizes are parameters such as the number of zones. They expand when a sequence is instantiated for a building:
- a vector connector becomes numbered scalar connectors;
- a vectorized child becomes one child per element;
- an array class child expands onto existing comps, as [Blocks](Blocks.md) describes.

A vectorized child carries its size in `cdlArraySize`. An array class child is typed as its `kw.cdl` spec:

```
mulMax: kw.cdl::RealsMultiMax? <cdlInstance, cdlName:"mulMax", cdlOf:@kw.cdl::cdl-RealsMultiMax, cdlBind:{nin:"nZon"}, cdlFinalBind:"nin"> {
```

# Top-level composites

21 composites are top level: no other composite nests them. They are what a building instantiates. The seven that carry `cdlExpand` are all among them, and no nested composite expands.

| Composite | `cdlExpand` |
|-|-|
| `kw.cdl.g36.ahu::AhusMultiZoneVavController` | |
| `kw.cdl.g36.ahu::AhusSingleZoneVavController` | |
| `kw.cdl.g36.ahu::FanCoilUnitsController` | |
| `kw.cdl.g36.ahu::AhusMultiZoneVavSetPointsOutdoorAirFlowAshrae62_1SumZone` | yes |
| `kw.cdl.g36.ahu::AhusMultiZoneVavSetPointsOutdoorAirFlowTitle24SumZone` | yes |
| `kw.cdl.g36.ahu::AhusMultiZoneVavSetPointsReliefFanGroup` | yes |
| `kw.cdl.g36.ahu::AhusSingleZoneVavSetPointsReliefFanGroup` | yes |
| `kw.cdl.g36.common::ThermalZonesAlarms` | |
| `kw.cdl.g36.common::ZoneGroupsGroupStatus` | yes |
| `kw.cdl.g36.common::ZoneGroupsZoneGroupSystem` | yes |
| `kw.cdl.g36.common::ZoneGroupsZoneStatusDuplicator` | yes |
| `kw.cdl.g36.terminal::TerminalUnitsCoolingOnlyController` | |
| `kw.cdl.g36.terminal::TerminalUnitsDualDuctColdDuctMinController` | |
| `kw.cdl.g36.terminal::TerminalUnitsDualDuctMixConDischargeSensorController` | |
| `kw.cdl.g36.terminal::TerminalUnitsDualDuctMixConInletSensorController` | |
| `kw.cdl.g36.terminal::TerminalUnitsDualDuctSnapActingController` | |
| `kw.cdl.g36.terminal::TerminalUnitsParallelFanCVFController` | |
| `kw.cdl.g36.terminal::TerminalUnitsParallelFanVVFController` | |
| `kw.cdl.g36.terminal::TerminalUnitsReheatController` | |
| `kw.cdl.g36.terminal::TerminalUnitsSeriesFanCVFController` | |
| `kw.cdl.g36.terminal::TerminalUnitsSeriesFanVVFController` | |

The controllers have no arrays. The multiple-zone controller takes zone totals through scalar connectors, such as `VSumAdjPopBreZon_flow` and `uZonTemResReq`, which are computed outside it. The SumZone composites compute the airflow totals.

# Nested composites

A composite child stays nested in the library. It runs best flattened: [Resolver](Resolver.md) explains why, and how the resolver does it.

# Parameters in forms

Guideline 36 controllers have many parameters, and most apply only in some configurations. Each parameter carries MBL's dialog information:
- `cdlEnable`: when it applies;
- `cdlGroup` and `cdlTab`: where a form shows it.

A configuration tool can build its form from these tags alone.
