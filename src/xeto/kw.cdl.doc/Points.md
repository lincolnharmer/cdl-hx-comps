<!--
title:      Points
author:     Lincoln Harmer
created:    1 Nov 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

A CDL connector carries a unit and a quantity, but not what it is. `TZon` is a temperature in kelvin. It does not say that it is a zone air temperature sensor.

The Guideline 36 libraries add that. Each connector that reads or writes a building point names the Project Haystack point spec that answers it. Binding a sequence to a building then becomes a query per connector.

The point specs come from Project Haystack's `ph.points` and `ph.points.x` libraries, which build on `ph`. The libraries depend on no other building ontology.

# The meta

| Tag | Meaning |
|-|-|
| `cdlPointSpec` | The point spec that answers the connector, a `Ref` to a spec |
| `cdlPointSpecCases` | The same, where the spec depends on an enumeration parameter: one `{when, pointSpec}` per case |
| `cdlPointScope` | The equipment the point belongs to |
| `cdlPointUnit` | On a unit `1` slot: the unit its number is counted in at the point, `ppm` or `%` |
| `cdlPointScale` | On a unit `1` connector whose point specs carry `%`: the factor from the point's value to the slot's, `0.01` |

511 connectors carry `cdlPointSpec` and 25 carry `cdlPointSpecCases`. Each of those 536 carries `cdlPointScope`.

21 more connectors resolve to a case spec but carry no point meta. Their spec depends on the `heaCoi`, `cooCoi` or `minOADes` parameter, and they sit in composites nested inside a controller, such as `yVal` of `TerminalUnitsReheatSubsequencesDamperValves`. Those composites do not declare the parameter the case reads, so the case cannot be written there. The controller that wraps each one declares it and carries `cdlPointSpecCases` on its own connector, and a binder binds the controller.

A plain spec, from `TerminalUnitsCoolingOnlyController`:

```
// Measured room temperature
tZon: hx.comps::StatusNumber? <cdlInput, cdlName:"TZon", cdlType:"Real", cdlUnit:"K", cdlQuantityKind:"ThermodynamicTemperature", quantity:"temperature", cdlPointSpec:ph.points::ZoneAirTempSensor, cdlPointScope:"zone">
```

A spec that depends on the heating coil type:

```
yVal: hx.comps::StatusNumber? <cdlOutput, cdlName:"yVal", cdlType:"Real", cdlUnit:"1", unitless, cdlMin:"0", transient, readonly, cdlPointSpecCases:List {{when:"heaCoi == Buildings.Controls.OBC.ASHRAE.G36.Types.HeatingCoil.WaterBased", pointSpec:ph.points.x::HotWaterValveModulatingCmd}, {when:"heaCoi == Buildings.Controls.OBC.ASHRAE.G36.Types.HeatingCoil.Electric", pointSpec:ph.points::HeatModulatingCmd}}, cdlPointUnit:"%", cdlPointScale:"0.01", cdlPointScope:"self", link:"setOve.yVal">
```

`when` is a CDL expression in the composite's parameters. In a valid configuration at most one case holds.

# Scope

A spec alone does not pick out one point. A terminal unit controller reads two discharge air temperatures: its own (`TDis`) and the air handler's (`TSup`). Both are `ph.points.x::DischargeAirTempSensor`:

```
tDis: hx.comps::StatusNumber? <cdlInput, cdlName:"TDis", ..., cdlPointSpec:ph.points.x::DischargeAirTempSensor, cdlPointScope:"self">
tSup: hx.comps::StatusNumber? <cdlInput, cdlName:"TSup", ..., cdlPointSpec:ph.points.x::DischargeAirTempSensor, cdlPointScope:"upstreamAir">
```

`cdlPointScope` says which equipment the point belongs to:

| Scope | The point belongs to |
|-|-|
| `self` | The controlled unit |
| `upstreamAir` | The air handler that feeds it |
| `upstreamAir(coldDeck)`, `upstreamAir(hotDeck)` | One deck of that air handler, on a dual-duct unit |
| `zone` | The zone the unit serves |
| `perZone` | One zone of an array of zones |
| `perReliefFan`, `perSupplyFan` | One fan of an array of fans |

The scope names a relationship. How a building records it (equipment refs, a system model) is the binder's business, not the class's.

# Binding

Binding a sequence to a building is a separate step from the libraries, and no binder is in this repo. The rule the meta is written for:
- For each connector with a point spec, query the building for points of that spec within its scope.
- Exactly one match binds.
- None, or more than one, is reported and refused.
- Nothing is inferred.

A `%` point scales at the boundary by `cdlPointScale`. A ppm point binds as it is. See [Units](Units.md).

# What is deliberately unbound

Some connectors carry no point spec on purpose:
- **Signals between sequences.** A value one sequence computes and another reads, such as the operating mode `uOpeMod` or a zone heating setpoint `THeaSet` passed into a terminal unit controller, is wired sequence to sequence. It is not a building point.
- **Operator overrides.** Inputs such as `oveFloSet`, `oveDamPos` and `oveFan` carry no spec. Project Haystack models an override as a priority-array write, not as a separate point. A site that wants them can bind soft points.
- **Alarms.** Alarm outputs such as `yLowFloAla` carry no spec. They belong to an alarm or fault layer, not to a point.

Some point connectors have no spec because `ph` cannot name them yet. The largest groups are the relief fan points, the cold and hot deck supply temperatures a dual-duct terminal unit reads (`TColSup`, `THotSup`), and the occupant setpoint adjustments (`setAdj`, `cooSetAdj`, `heaSetAdj`).

# Relief equals exhaust

`ph` has no relief marker. A relief damper command binds to the matching exhaust air damper spec, `ph.points.x::ExhaustAirDamperModulatingCmd` or `ph.points.x::ExhaustAirDamperOpenCmd`:

```
yRelDam: hx.comps::StatusNumber? <cdlOutput, cdlName:"yRelDam", ..., cdlPointSpec:ph.points.x::ExhaustAirDamperModulatingCmd, cdlPointUnit:"%", cdlPointScale:"0.01", cdlPointScope:"self", ...>
```

Both dampers move air out of the building, and the exhaust damper specs are the nearest `ph` names. A `relief` marker would let a model tell the two apart, and is a question for Project Haystack. Relief fan points carry no spec yet.

# The Project Haystack version

The point specs were chosen against Project Haystack's xeto repository at commit `23be968cdf07dd23ce59c69a159608084c363451`. Every spec they name also exists at commit `8ba9d7ffc3fe8ace52070f9b0bdc9239ad36a9f5`, which the libraries are compiled against.

# Open points for Project Haystack

- A `relief` marker for dampers and fans.
- Point specs for the gaps above.
- One window sensor sense. CDL `u1Win` is true when the window is closed. `ph.points::WindowOpenSensor` is true when it is open, so a binder must invert it.
