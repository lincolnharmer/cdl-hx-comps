<!--
title:      Meta
author:     Lincoln Harmer
created:    31 Oct 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

`kw.cdl` declares 63 meta tags, in `meta.xeto`. Every generated spec in the four libraries draws its CDL meta from this set. This chapter lists them all, grouped. `meta.xeto` holds the exact rule behind each one.

The specs also carry standard Xeto and `sys.comp` meta that `kw.cdl` does not declare: `abstract`, `key`, `unit`, `quantity`, `unitless`, `minVal`, `maxVal`, `transient`, `readonly`, `link` and `loopCut`.

The tables say where a tag appears. A *parameter* is a slot marked `cdlParam`, a *connector* one marked `cdlInput` or `cdlOutput`, and a *child* one marked `cdlInstance` or `cdlFeed`.

# Identity

| Tag | Meaning |
|-|-|
| `cdlClass` | The MBL class path a spec was generated from |
| `cdlElementary` | Marks a spec generated from a CDL elementary class (the array classes) |
| `cdlClause` | The Clause 7 number of an elementary class, such as `7.5.29.1` |
| `cdl231Name` | Clause 7's spelling of a class where it differs from MBL's, such as `CDL.Reals.Multisum` |

# Slots

| Tag | Meaning |
|-|-|
| `cdlParam` | Marks a CDL parameter |
| `cdlInput` | Marks a CDL input connector |
| `cdlOutput` | Marks a CDL output connector |
| `cdlInstance` | Marks a child that is a contained CDL instance |
| `cdlName` | The CDL name of a slot, before its first letter was lowered for Xeto |
| `cdlType` | The CDL data type: `Real`, `Integer`, `Boolean`, or an enumeration spec qname |
| `cdlDefault` | A parameter default written as an expression of other parameters, such as `fill(1,nin)` |
| `cdlProtected` | Marks a protected parameter, computed at expansion and never stored on a record |
| `cdlFinal` | Marks a final parameter, which a design modifier must not override |

# Composites

| Tag | Meaning |
|-|-|
| `cdlOf` | On a child: the `CdlClass` instance of the elementary class it runs, such as `@kw.cdl::cdl-RealsLimiter` |
| `cdlBind` | On a child: its bindings that stay expressions in the composite's parameters, CDL parameter to expression. A literal binding on a comp child is written as the comp slot's value instead. |
| `cdlFinalBind` | The bindings of a child that MBL marks final, as comma-separated slot names |
| `cdlDefaulted` | On a child: the CDL parameters the generator wrote from the CDL default because the instance leaves them unbound |
| `cdlFeed` | On a comp the generator adds beside a child: the child and the CDL parameter or connector it supplies, as `inst.name` |
| `cdlCondition` | The guard of a conditional child or connector, a CDL expression |
| `cdlAltLink` | Alternative drivers of one sink, comma-separated, each on a conditional child or connector |
| `cdlArraySize` | The size of a vector connector or a vectorized child, a CDL expression such as `nZon` |
| `cdlExpand` | Marks a spec that expands when a sequence is instantiated: an array class, or a composite that holds a vector connector, a vectorized child, or a child that expands |
| `cdlLinkVia` | On a link that replaced CDL instances whose class compiles to a link (IntegerToReal, Pre): their names, nearest the target first |

# Units

[Units](Units.md) explains how these fit together.

| Tag | Meaning |
|-|-|
| `cdlUnit` | The CDL unit as MBL declares it, such as `K`, `s`, `Pa`, `m³/s` or `1`, or as corrected where `cdlUnitOverride` is present |
| `cdlQuantityKind` | The QUDT quantity kind as CXF writes it, such as `ThermodynamicTemperature` |
| `cdlQuantityInferred` | Marks a `K` slot whose kind (absolute or difference) neither CXF nor MBL states, taken from MBL's display unit or a recorded decision |
| `cdlUnitInferred` | The CDL unit of a slot MBL declares with no unit, taken from a recorded decision or a binding |
| `cdlUnitVia` | On a parameter with an inferred unit: the instance path of the contained parameter it was bound into and took the unit from |
| `cdlUnitOverride` | On a slot whose MBL unit was corrected: the unit MBL declares. `cdlUnit` holds the corrected one. |
| `cdlDelta` | Marks a temperature difference. A difference converts by scale, an absolute temperature with the offset. |
| `cdlConnUnits` | On a child: its units on its own connectors, where MBL types a polymorphic block per instance |
| `cdlLiteralUnits` | On a child: the unit of each literal the generator wrote on it, slot to Haystack unit symbol (`K`, `sec`), `1` for a dimensionless value |
| `cdlLiteralDelta` | The literals of `cdlLiteralUnits` that are differences, comma-separated |
| `cdlLiteralExprs` | The MBL expression a literal was evaluated from, such as `273.15 +24` or a package constant |
| `cdlCompoundGain` | On a child run on its class's compound gain comp because its gain's unit is not in the unit database: `{unit, gain, per, perGroup}` |
| `cdlUnitGroup` | On a feed: the CDL connector whose unit group the feed's value converts with |

# Points

[Points](Points.md) explains how these are used.

| Tag | Meaning |
|-|-|
| `cdlPointSpec` | On a connector that reads or writes a building point: the Project Haystack point spec that answers it |
| `cdlPointSpecCases` | The same, where the spec depends on an enumeration parameter: one `{when, pointSpec}` per case |
| `cdlPointScope` | On a connector with a point spec: the equipment the point belongs to, such as `self`, `upstreamAir` or `zone` |
| `cdlPointUnit` | On a slot declared unit `1`: the unit its number is counted in at the point, `ppm` or `%` |
| `cdlPointScale` | On a unit `1` connector whose point specs carry `%`: the factor from the point's value to the slot's, `0.01` |

# Bounds

| Tag | Meaning |
|-|-|
| `cdlMin`, `cdlMax` | A connector's declared minimum and maximum |
| `cdlMinConst`, `cdlMaxConst` | The MBL expression a bound was resolved from, where MBL writes it with a constant, such as `100*Constants.eps` |
| `cdlMinVia`, `cdlMaxVia` | The instance path of the contained parameter whose bound a parameter carries |
| `cdlMinOwn`, `cdlMaxOwn` | MBL's own bound on a parameter where a block downstream is tighter and the stored bound carries the tighter number |
| `cdlMinWhen`, `cdlMaxWhen` | Bounds that only guarded instances impose, as `CdlBoundWhen` items: `{val, cond, via}` |
| `cdlMinExpr`, `cdlMaxExpr` | A bound written as an expression of the class's other parameters, which no static number can hold |
| `cdlSiMin`, `cdlSiMax` | On a parameter shown in its bound point's unit: the SI bound, as a Number with its unit, in place of `minVal` and `maxVal` |

A parameter's hard bound is its `minVal` or `maxVal`, or `cdlSiMin` or `cdlSiMax` on a converted slot. The other tags say where a bound came from, or carry bounds no static number can hold. At MBL 14.0.0 no slot carries `cdlMaxOwn`.

# Forms

| Tag | Meaning |
|-|-|
| `cdlEnable` | MBL's `Dialog(enable)`: the condition under which a parameter applies |
| `cdlGroup` | MBL's `Dialog(group)`: the group a form shows the parameter under |
| `cdlTab` | MBL's `Dialog(tab)`: the tab a form shows the parameter on |
| `cdlValueInReference` | MBL's `__cdl(ValueInReference)`: whether MBL's reference results carry the parameter's value |

A configuration tool can build its form from these tags alone.

# State

| Tag | Meaning |
|-|-|
| `cdlState` | Whether an elementary class holds state, read from MBL's equations: `stateful`, `stateless` or `undecided` |
| `cdlStateInit` | On a stateful class: `readsInput` when an output's initial value reads an input, else `noInput` |
| `cdlStateInitBasis` | On a `noInput` class: why, as `noInputConnector`, `preDelayed` or `parameterInit` |
| `cdlStateBasis` | On a class that is not stateless: the constructs and instances behind `cdlState` |

The array classes carry these tags on their specs. Every `CdlClass` instance, array classes included, carries the same facts as `state`, `stateInit`, `stateInitBasis` and `stateBasis`, and so does each entry of `@cdl-refused`.
