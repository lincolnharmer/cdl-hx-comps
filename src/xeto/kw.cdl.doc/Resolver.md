<!--
title:      Resolver
author:     Lincoln Harmer
created:    1 Nov 2026
copyright:  Copyright (c) 2026, kW Engineering
license:    Licensed under the Academic Free License version 3.0
-->

# Overview

A Guideline 36 composite cannot run as it stands. It still carries CDL parameter expressions, conditions, alternative links and array sizes, and those depend on how one piece of equipment is configured. Instantiating a sequence turns one configured composite into a concrete comp graph that `hx.comps` runs as is.

Instantiation needs:
- the parameter values for one piece of equipment, in CDL names;
- each remaining parameter from its default or its `cdlDefault` expression;
- every `cdlCondition` evaluated, with absent children, connectors and their links dropped;
- each `cdlAltLink` sink given the one driver that is present;
- every `cdlBind` evaluated and written to its comp slot or feed, converted per the child's `CdlClass`;
- every array expanded, for a `cdlExpand` composite;
- every value given its unit, and converted where a point unit reaches it ([Units](Units.md));
- every bound checked.

It needs nothing from the building except, optionally, the unit of each bound point. Binding connectors to a building's points is a separate step that takes the resolved graph as input ([Points](Points.md)).

# The resolver pod

The resolver is the pod `cdlResolve`, in this repo under `src/fan/cdlResolve`.

The pod depends only on Fantom and Haxall pods: `sys`, `concurrent`, `util`, `xeto`, `haystack`, `axon`, `hx` and `hxComps`. It binds a small Xeto library, `kw.cdl.resolve`, which declares the Axon function and depends on `sys`, `axon` and `hx`.

## Fantom

```
CdlResolver(Namespace ns)
Dict CdlResolver.resolve(Str qname, Dict params, Dict? opts := null)
Dict CdlResolver.resolveSpec(Spec spec, Dict params, Dict? opts := null)
static Str CdlResolver.toXeto(Namespace ns, Dict graph)
```

- `ns` is a namespace holding `hx.comps`, `kw.cdl` and the Guideline 36 libraries.
- `qname` names a composite, such as `kw.cdl.g36.terminal::TerminalUnitsCoolingOnlyController`. `resolveSpec` takes the spec instead.
- `params` gives parameter values by CDL name, such as `VCooMax_flow` rather than its slot name `vCooMax_flow`. A Real may carry a unit, and converts to SI. A temperature difference given in a unit with an offset must use the delta unit, such as `Δ°F`, not `°F`. A number with no unit is taken as SI. An enumeration parameter takes its CDL key, such as `ASHRAE62_1` or `WaterBased`, not the Xeto item name.
- `toXeto` writes the graph as Xeto instance text, which `CompSpace.loadXeto` loads keeping every comp id.

## Axon

```
cdlResolve(qname, params, opts)
```

For example:

```
cdlResolve("kw.cdl.g36.common::GenericTimeSuppression", {})
```

The same composite with Fahrenheit points, from Fantom:

```
CdlResolver(ns).resolve("kw.cdl.g36.common::GenericTimeSuppression", Etc.dict0,
  Etc.dict1("pointUnits", Etc.dict2("TSet", "°F", "TZon", "°F")))
```

In that graph `gai` writes `chaRat` as 540 sec, unconverted, and its 1 K point as 1.8 Δ°F ([Units](Units.md)).

## Options

| Option | Meaning |
|-|-|
| `pointUnits` | A dict of input or output connector, by CDL name, to the unit of the point bound to it, as a Str symbol or a Unit. Each unit group a point unit reaches is resolved in that unit, and every literal and parameter value in it converts. With none, every value stays SI. A difference connector needs a delta unit, and a unit `1` connector takes only its `cdlPointUnit`. |
| `id` | The root id, and the prefix of every comp id. The default is `cdl`. |

## Output

The result is `sys.comp` data: one `hx.comps::Folder` whose children are `hx.comps` comps.

- Each comp is named by its instance path in Xeto slot names, with `.` and brackets turned to `_`, because `sys.comp` refuses a dot in a name. `conTSup.conPID` becomes `conTSup_conPID`, and `booToInt[2]` becomes `booToInt_2`. Two paths that flatten to one name refuse.
- Each comp keeps its dotted path in CDL spelling in `cdlPath`. The point comp for `TSup` is named `tSup`, with `cdlPath` `TSup`.
- Comps the resolver adds, such as the nodes of an expanded array tree, carry names derived from the instance they serve.
- Each comp's id is `<id>-<name>`, so a re-resolve with new parameters keeps every id.
- Each input connector of the composite becomes a `NumberPointInput` or `BoolPointInput` comp, one per element of an array connector. Each output connector becomes a `NumberPointOutput` or `BoolPointOutput`. They carry `bindSpec` (the connector's point spec), `cdlName`, `cdlUnit`, and `pointUnit`, `cdlPointScope`, `cdlPointUnit` and `cdlPointScale` where they apply.
- A link that runs through a `loopCut` keeps it.

The resolver does not scale a `%` point. The point comp carries `cdlPointScale`, and the binder applies it at the boundary.

## Refusals

Every refusal raises `CdlResolveErr`, naming the parameter, expression, child, connector or unit group, and why. The resolver never guesses. It refuses, for example, when:
- a parameter has no value and no default, and its `cdlEnable` does not exempt it;
- a value is given for a `cdlFinal` or `cdlProtected` parameter;
- a value is outside its bounds: `minVal`, `maxVal`, `cdlSiMin`, `cdlSiMax`, a `cdlMinWhen` or `cdlMaxWhen` case whose condition holds, or a `cdlMinExpr` or `cdlMaxExpr`;
- an expression is outside the grammar;
- none, or more than one, of a sink's alternative drivers is present;
- a child runs an array class with no comp: `Sort` or one of the three `TimeTable` classes;
- an array instance is out of reach of its expansion, such as an `Extractor` over more than 10 inputs or a `MultiMax` or `MultiMin` with no inputs;
- a child is a vectorized composite (none occurs in the Guideline 36 libraries);
- a point unit does not fit its connector;
- a unit group reaches two point units, or holds a value it cannot convert.

## Expressions

Bindings, conditions, defaults, array sizes and bounds are CDL expressions. The resolver reads:
- `if c then a else b`, without `elseif`;
- `or`, `and` and `not`;
- one comparison, `< <= > >= == <>`;
- `+ - * /` and unary minus;
- numbers, `true`, `false`, names, and dotted names for enumeration items and package constants;
- lists `{ }`, matrices `[ ; ]`, ranges `a:b`, `fill(v, n)`, `fill(v, n, m)` and `size(a, 1|2)`.

Anything else refuses with the whole expression quoted. The grammar is held to one table of accepted and refused cases, the same table the libraries' generator is tested against.

## Arrays

For a `cdlExpand` composite, vector connectors and vectorized children expand to their resolved sizes, in one or two dimensions. Each array class child expands onto existing comps:
- **Reductions** (`MultiSum`, `MultiMax`, `MultiMin`, `MultiAnd`, `MultiOr`) become a balanced tree of the 4-input comps. `MultiSum` adds a `Multiply` or `Negative` comp for each gain other than 1 or 0, drops an input whose gain is 0, and with no inputs gives 0.
- **`MatrixGain`** becomes one `Add` tree per row over its nonzero entries. `MatrixMax` and `MatrixMin` become one `Maximum` or `Minimum` tree per row or column.
- **Routing** (the replicators, `VectorFilter`, `ExtractSignal`) is wiring and makes no comp. `Extractor` becomes one select comp.

Every comp an expansion makes carries the instance's path.

# Why the graph is flat

The resolver writes one flat graph, with no nested composites. A nested composite runs, but not in the order CDL expects.

The `sys.comp` runtime in Haxall mounts nested comps into one map and orders them with Kahn's algorithm (`CompMap.sortByTopology`). A link from a composite input to a child, plus a link from a child to the composite output, closes a cycle in that sort. Every comp in a cycle, and everything downstream of one, then runs in hash order of its comp id. A value crossing a composite boundary can wait from one execute up to the length of the chain, and the wait changes whenever ids change.

A flat graph has no composite slots, so it sorts topologically, and a chain settles within one execute.

# Pre seeding

`Logical.Pre` compiles to a `loopCut` link (see [Blocks](Blocks.md)). A `loopCut` link reads null on the first cycle, where MBL reads `pre_u_start`. A latch or switch that starts from null can stay null for many cycles.

So where a link runs through a Pre, the resolver writes the Pre's `pre_u_start` as the starting value of the target slot, `false` unless MBL binds it, and marks the comp with `cdlPreSeed` naming the slot. From the second cycle on, the link delivers the previous cycle's value, as in MBL.

# Validation

The resolver was run against MBL 14.0.0's own validation models for every air-side Guideline 36 controller: the 14 controller validation models (AHU, fan coil and terminal unit), which hold 17 controller instances. Each resolved graph was driven with the validation model's inputs at a 0.1 s step and compared with MBL's Dymola reference results.

- 158 outputs are recorded by the references, at 101 samples each. 131 agree within 1e-5 x max(1, |ref|) at every sample.
- All 158 agree within 1e-3 x max(1, |ref|) at every sample. That is the default tolerance of the BuildingsPy regression tester MBL's own tests run, applied pointwise.
- Of the 27 outputs that differ beyond 1e-5, 5 are explained by step size or by a documented comp departure. 22, up to 6.5e-4, are not yet explained.
- A one-step timing lag would show against these references in only 24 of the 158 outputs, all among the 27 that differ.
- The plant controllers were not run.

# Not done

- **Layout.** The libraries carry no CDL placement, so the output carries no `compLayout`.
- **Binding.** The resolver does not bind points. That is a separate step.
