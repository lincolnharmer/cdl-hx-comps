<!--
title:      Units
author:     Lincoln Harmer
created:    1 Nov 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

CDL values are SI. A temperature is in kelvin, a pressure in pascals and a flow in cubic metres per second, and every default and literal in MBL is written that way.

A building's points often are not. A zone temperature may be in °F, a duct static pressure in inH₂O, an airflow in cfm. The libraries do not convert anything. They record enough for a resolver to show each block's values in the unit of the point it is bound to, and to convert every parameter and literal on the way.

The rule:
- A block shows values in the unit of the point bound to it.
- Every slot joined to that point through links and unit rules (a *unit group*) inherits the point's unit.
- Everything else stays SI.

# How a slot records its unit

| Unit | Meta on the slot |
|-|-|
| `K`, absolute | `cdlUnit:"K"`, `quantity:"temperature"`, no `unit` |
| `K`, difference | `cdlUnit:"K"`, `cdlDelta`, no `quantity`, no `unit` |
| `Pa`, `m³/s`, `J/kg` | `cdlUnit`, and `quantity` (`pressure`, `volumetricFlow`, `specificEnthalpy`), no `unit` |
| `s` | `cdlUnit:"s"`, `unit:"sec"`, `quantity:"time"` |
| `1` | `cdlUnit:"1"`, `unitless` |
| `1/K`, `s/K` | `cdlUnit` or `cdlUnitInferred` only. Neither is in the unit database. |
| none | Neither `unit` nor `unitless`. A generic connector serves every quantity, and its unit is set per instance. |

These are the only CDL units the four libraries use. `cdlUnit` is MBL's declared unit, except where `cdlUnitOverride` records a correction, and `cdlQuantityKind` is the QUDT kind CXF writes. A slot with an inferred unit carries it in `cdlUnitInferred` instead of `cdlUnit` (below).

**Why no `unit` on converted slots.** `xeto fits` checks `unit` by exact match. A slot that a resolver shows in a °F, inH₂O or cfm point would carry `unit:"K"` and refuse the converted value. So those slots carry `quantity` instead, which `fits` checks against the value's own unit.

**Why a temperature is always `K`.** CDL spells an absolute temperature and a temperature difference the same way, `K`. They convert differently: an absolute value with the offset, a difference by scale alone. A difference carries the `cdlDelta` marker. It carries no `quantity`, because no one Haystack quantity fits both `K` and a Fahrenheit difference.

```
// Near zero temperature difference, below which the difference will be seen as zero
dTHys: Number? <cdlParam, cdlName:"dTHys", cdlType:"Real", cdlUnit:"K", cdlQuantityKind:"TemperatureDifference", cdlDelta, cdlTab:"Advanced", cdlValueInReference:"false"> "0.25"
```

## Inferred units

MBL declares some Real parameters with no unit. Where the generator can tell the unit, it records it in `cdlUnitInferred` and leaves `cdlUnit` off, since MBL states none. The unit comes from one of two places:
- **A recorded decision**, naming the MBL declaration it is read from.
- **A binding.** A parameter bound by bare name into a contained parameter that declares a unit takes that unit. So does one bound into an elementary block whose `unitRule` ties it to a connector of known unit. `cdlUnitVia` names the contained parameter.

```
// Gain of controller for valve control
kVal: Number? <cdlParam, cdlName:"kVal", cdlType:"Real", cdlUnitInferred:"1/K", cdlUnitVia:"damVal.kVal", minVal:"1e-13", cdlMinVia:"damVal.conVal.k", ...> "0.5"
```

`cdlQuantityInferred` marks a `K` slot whose kind, absolute or difference, MBL does not state. The generator took the kind from MBL's display unit or from a recorded decision.

## Corrected units

Where MBL declares a unit wrongly, the generator corrects it only from a recorded decision. The slot keeps MBL's unit in `cdlUnitOverride`, and `cdlUnit` holds the corrected one. At MBL 14.0.0 one parameter is corrected, in two classes: `damPosHys` in the SeriesFanCVF and SeriesFanVVF `DamperValves` subsequences, a damper-position hysteresis that MBL declares in m³/s.

```
damPosHys: Number? <cdlParam, cdlName:"damPosHys", cdlType:"Real", cdlUnit:"1", cdlUnitOverride:"m³/s", unitless, cdlTab:"Advanced", cdlValueInReference:"false"> "0.05"
```

## Per-instance units

Some CDL blocks are polymorphic: `Reals.Subtract` subtracts pascals in one place and flows in another. Where MBL types an instance's connectors, the child records them in `cdlConnUnits`:

```
conErr: hx.comps::Subtract? <cdlInstance, cdlName:"conErr", cdlOf:@kw.cdl::cdl-RealsSubtract, cdlConnUnits:{u1:"Pa", u2:"Pa", y:"Pa"}> {
```

# Literals

The generator records the unit of the literals it writes on a child in `cdlLiteralUnits`, slot to Haystack unit symbol, with `1` for a dimensionless value. The units are SI, spelled the Haystack way where it differs (`sec`, `/s`). A literal whose unit the generator cannot tell carries none. `cdlLiteralDelta` names the literals that are differences. Where the comp slot takes a unit, the value carries a suffix too. `cdlLiteralExprs` keeps the MBL expression a literal was evaluated from.

```
conZer: hx.comps::NumberConst? <cdlInstance, cdlName:"conZer", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out", cdlFinalBind:"k"> {
  out: hx.comps::StatusNumber { val: 0K }
}
con: hx.comps::NumberConst? <cdlInstance, cdlName:"con", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"K"}, cdlLiteralExprs:{out:"273.15 +24"}, cdlFinalBind:"k", cdlCondition:"eneStd == Buildings.Controls.OBC.ASHRAE.G36.Types.EnergyStandard.ASHRAE90_1"> {
```

A temperature literal is written in `K` whether it is absolute or a difference, since `hx.comps` takes `K` less `K` as `K` and refuses `K` plus a `K` difference.

This matters at run time. On `hx.comps`, a `K` literal meeting a °F signal faults in arithmetic, in a comparator deadband and in `Hysteresis`. `Limiter` and `Line` convert it, which is right for the absolute values they take. So the resolver converts each literal into its group's unit before the sequence runs.

# Unit rules

Each `CdlClass` instance carries a `unitRule` that says how the class carries units, so a resolver can propagate them:

| Family | Meaning | Example |
|-|-|-|
| `A` | Keeps one unit across the names in each `keep` group | Limiter: `keep:"u,uMin,uMax,y"` |
| `B` | Compares values of one unit. Its hysteresis or error scale is their difference (`op:"delta"`). | PID: `keep:"u_s,u_m"`, `op:"delta"`, `ins:"u_s"`, `out:"r"` |
| `C` | Computes its output's unit from its inputs with `op` | Add: `op:"add"`, `ins:"u1,u2"`, `out:"y"` |
| `D` | Math on dimensionless numbers, or a class whose unit the rule leaves to its declarations or to a compound unit (`Derivative`, `SpecificEnthalpy_TDryBulPhi`) | |
| `E` | Carries Integers or counts | |
| `F` | Carries Booleans and declared times | |
| `array` | An array class, expanded first | MultiSum: `op:"sum"` |

`seeds` fixes a name's unit where the declaration does not, such as `{y:"1"}` on IntegerToReal: a count is dimensionless.

# Control signals and percent points

CDL control signals are fractions from 0 to 1: damper positions, valve commands, fan speeds. They stay fractions inside the sequence. A Project Haystack modulating point carries `%`.

A unit `1` connector whose point specs carry `%` says so, and gives the scale:

```
yDam: hx.comps::StatusNumber? <cdlOutput, cdlName:"yDam", cdlType:"Real", cdlUnit:"1", unitless, cdlMin:"0", transient, readonly, cdlPointSpec:ph.points.x::DischargeAirDamperModulatingCmd, cdlPointUnit:"%", cdlPointScale:"0.01", cdlPointScope:"self", link:"dam.yDam">
```

A binder multiplies the point's value by `cdlPointScale` on the way in, and divides by it on the way out. The scaling happens at the boundary, never inside the sequence.

The CO2 slots are counted in ppm. They carry `cdlPointUnit:"ppm"` and bind a ppm point as it is, with the slot's value written unitless.

# PID gains

A PID's `k`, `r`, `yMax` and `yMin` are Float slots on `hx.comps::CdlPid`. They carry no unit, and they neither fault nor convert.

- **`r` converts.** `r` scales the control error, so it is a difference in the unit of the setpoint. 5 K is 9 Fahrenheit degrees. The comp cannot catch a conversion that was missed, so every PID whose setpoint carries a unit writes `r`, at its binding or MBL's default of 1, with its unit recorded (`writeWhenUnit:"r"` on the class).
- **`k` does not convert.** In Guideline 36 every `1/K` is the `k` of a PID. Converting `r` alone converts the loop, so a `1/K` is provenance only.

```
conVal: hx.comps::CdlPid? <cdlInstance, cdlName:"conVal", cdlOf:@kw.cdl::cdl-RealsPidWithReset, cdlBind:{controllerType:"controllerTypeVal", k:"kVal", td:"TdVal", ti:"TiVal"}, cdlDefaulted:"y_reset,r", cdlLiteralUnits:{yReset:"1", yMax:"1", yMin:"1", r:"K"}, cdlLiteralDelta:"r", cdlFinalBind:"controllerType,k,td,ti,yMax,yMin", cdlConnUnits:{u_m:"K", u_s:"K"}> {
  yReset: 0
  yMax: 1
  yMin: 0
  r: 1
  inReset: <link:"greThr2.out">
  inMeasurement: <link:"tDis">
  inSetpoint: <link:"conTDisHeaSet.out">
}
```

# Compound gains

`Generic.TimeSuppression` multiplies a temperature change by `chaRat`, in seconds per kelvin. The unit database has no `s/K`. On `Multiply`, the product would take the unit of the input, `K`, and then meet seconds in a comparison and fault.

So that child runs on `Line` instead, through (0, 0) and (1 K, `chaRat` s), and `Line` gives its output the unit of its second axis, seconds. The class records this in `compoundGain`, and the child carries `cdlCompoundGain`:

```
gai: hx.comps::Line? <cdlInstance, cdlName:"gai", cdlOf:@kw.cdl::cdl-RealsMultiplyByParameter, cdlCompoundGain:{unit:"s/K", gain:"inF2", per:"inX2", perGroup:"u"}, cdlBind:{k:"chaRat"}, cdlFinalBind:"k"> {
  inF2: <link:"gai_k.out">
  in: <link:"abs2.out">
  inX1: <link:"gai_inX1.out">
  inF1: <link:"gai_inF1.out">
  inX2: <link:"gai_inX2.out">
  limitBelow: "false"
  limitAbove: "false"
}
gai_inX2: hx.comps::NumberConst? <cdlFeed:"gai.inX2", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out", cdlUnitGroup:"gai.u"> {
  out: hx.comps::StatusNumber { val: 1K }
}
```

The resolver writes `chaRat` in seconds, unconverted. It converts the 1 K point with the unit group of `u`, named by `cdlUnitGroup`, as a difference: 1.8 Fahrenheit degrees on a Fahrenheit building. The comp does not convert it, because `Line` refuses a difference beside an absolute value. 540 s per kelvin then acts as 300 s per Fahrenheit degree.

# Bounds on converted slots

`xeto fits` compares `minVal` and `maxVal` as bare numbers. An SI bound on a slot shown in °F would then be checked against the converted value. So a slot a resolver converts carries its bounds as `cdlSiMin` and `cdlSiMax` instead, Numbers in the SI unit. A resolver checks them before it converts.

```
dpBuiSet: Number? <cdlParam, cdlName:"dpBuiSet", cdlType:"Real", cdlUnit:"Pa", cdlQuantityKind:"Pressure", quantity:"pressure", cdlSiMax:"30Pa", cdlValueInReference:"true"> "12"
```

On such a slot, `cdlMinVia`, `cdlMinOwn`, `cdlMinWhen` and `cdlMinExpr` are in its `cdlUnit`.

# What xeto fits checks

`xeto fits` enforces `unit`, `quantity`, `unitless`, `minVal` and `maxVal` on a Number parameter. On a `List` parameter, an array, it checks only size.

It does not check:
- **Connectors.** A connector is an `hx.comps` status type, a Dict, and `fits` applies these tags only to scalars and lists. A connector's unit meta, `cdlMin` and `cdlMax` are information for a binder and a resolver, not a guard.
- **Differences.** A `cdlDelta` slot carries no `quantity` and no `unit`, so `fits` checks nothing about its unit. The resolver owns it.
- **Converted bounds.** `cdlSiMin` and `cdlSiMax` are `kw.cdl` meta, not Xeto bounds.
- **Conditional and expression bounds.** `cdlMinWhen`, `cdlMaxWhen`, `cdlMinExpr` and `cdlMaxExpr` depend on other parameters. A configuration tool or the resolver evaluates them.
- **`1/K` and `s/K` slots,** which carry no Xeto `unit`.
