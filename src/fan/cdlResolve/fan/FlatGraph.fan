//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** The flat comp graph: every comp, its values and its links, before it is
** written as `sys.comp` data
**
internal class FlatGraph
{
  ** Comps by flat name, in the order they were made
  Str:FlatComp comps := Str:FlatComp[:] { ordered = true }

  ** Add a comp. Two instance paths that flatten to one name refuse.
  FlatComp add(Str name, Str path, Str cdlPath, Spec spec, Dict? cls, Str kind)
  {
    if (!Etc.isTagName(name)) throw CdlResolveErr("instance path $path flattens to '$name', which is not a valid comp name")
    old := comps[name]
    if (old != null) throw CdlResolveErr("instance paths ${old.path} and $path both flatten to comp name $name")
    fc := FlatComp(name, path, cdlPath, spec, cls, kind)
    comps[name] = fc
    return fc
  }

  FlatComp? get(Str name) { comps[name] }

  ** The flat name of an instance path: `conLoo.conCoo` gives
  ** `conLoo_conCoo` and `booToInt[2]` gives `booToInt_2`
  static Str flatName(Str path)
  {
    path.replace("[", "_").replace("]", "").replace(",", "_").replace(".", "_")
  }

  ** The element names of connector `name` with shape `sh`, row-major:
  ** `u_1`, `u_2` or `u_1_1`, `u_1_2`
  static Str[] elemNames(Str name, Int[] sh)
  {
    if (sh.isEmpty) return [name]
    if (sh.size == 1) return (1..sh[0]).toList.map |k->Str| { "${name}_$k" }
    acc := Str[,]
    for (i := 1; i <= sh[0]; ++i) for (j := 1; j <= sh[1]; ++j) acc.add("${name}_${i}_$j")
    return acc
  }

  ** The CDL names of the elements of connector `name`: `u[1]`, `u[1,2]`
  static Str[] cdlElemNames(Str name, Int[] sh)
  {
    if (sh.isEmpty) return [name]
    if (sh.size == 1) return (1..sh[0]).toList.map |k->Str| { "${name}[$k]" }
    acc := Str[,]
    for (i := 1; i <= sh[0]; ++i) for (j := 1; j <= sh[1]; ++j) acc.add("${name}[${i},$j]")
    return acc
  }

  ** Write the graph as `sys.comp` data: one Folder holding every comp
  Dict emit(Namespace ns, Str rootId, Spec spec)
  {
    acc := Str:Obj?[:] { ordered = true }
    acc["id"] = Ref(rootId)
    acc["spec"] = Ref("hx.comps::Folder")
    acc["dis"] = spec.name
    acc["cdlSpec"] = spec.qname
    cls := spec.meta["cdlClass"]
    if (cls != null) acc["cdlClass"] = cls
    comps.each |fc|
    {
      d := Str:Obj?[:] { ordered = true }
      d["id"] = Ref("${rootId}-${fc.name}")
      d["spec"] = Ref(fc.spec.qname)
      d["cdlPath"] = fc.cdlPath
      fc.extra.each |v, n| { d[n] = v }
      fc.vals.each |pv, n| { if (pv.written != null) d[n] = pv.written }
      if (!fc.links.isEmpty)
      {
        links := Str:Obj[:]
        fc.links.each |l, slot|
        {
          from := Ref("${rootId}-${l.from.comp}")
          links[slot] = l.cut
            ? Etc.linkWrap(Etc.dict3("fromRef", from, "fromSlot", l.from.slot, "loopCut", Marker.val))
            : Etc.link(from, l.from.slot)
        }
        d["links"] = Etc.links(Etc.dictFromMap(links))
      }
      acc[fc.name] = Etc.dictFromMap(d)
    }
    return Etc.dictFromMap(acc)
  }
}

**
** One comp of the flat graph
**
internal class FlatComp
{
  new make(Str name, Str path, Str cdlPath, Spec spec, Dict? cls, Str kind)
  {
    this.name = name
    this.path = path
    this.cdlPath = cdlPath
    this.spec = spec
    this.cls = cls
    this.kind = kind
  }

  const Str name
  ** The CDL instance path in Xeto slot names
  const Str path
  const Str cdlPath
  ** The hx.comps comp
  Spec spec
  ** The CdlClass of the CDL class it runs, or null for a comp the
  ** resolver added
  Dict? cls
  ** comp, feed, input, output, scale or tree
  const Str kind
  ** Slot values, written after the unit pass
  Str:PVal vals := Str:PVal[:] { ordered = true }
  ** Incoming links by target slot
  Str:FlatLink links := Str:FlatLink[:] { ordered = true }
  ** Further slots written as they are (cdlName, cdlPart, ...)
  Str:Obj extra := Str:Obj[:] { ordered = true }
  ** The SI unit a slot is known to carry
  Str:Str siSeeds := [:]
  ** The temperature kind a slot is known to carry: true for a difference
  Str:Bool kindSeeds := [:]
  ** The units and kinds every connector a link crossed declares, by slot
  Str:Str[] siFacts := [:]
  Str:Bool[] kindFacts := [:]
  ** The gain unit of a child run on its class's compound gain comp (s/K)
  Str? compound
  ** The child's cdlCompoundGain, where it is a Dict
  Dict? compoundMeta
  ** The unit of the point bound to this comp, and its slot
  Unit? pointUnit
  Str? pointSlot
  ** The connector a point comp stands for
  Spec? conn
  ** A feed: the endpoint it supplies
  Ep? feedFor
  ** The unit rule of a comp the resolver added
  UnitRule? synth

  override Str toStr() { "$name [$spec.qname]" }
}

**
** A link into a flat comp's slot
**
internal const class FlatLink
{
  new make(Ep from, Bool cut) { this.from = from; this.cut = cut }
  const Ep from
  const Bool cut
}

**
** A value waiting for its unit: written once the unit pass knows the unit
** group of its slot
**
internal class PVal
{
  ** A literal the generator wrote, as the Fantom value of the slot
  static PVal literal(Obj? v, Str what) { make(v, null, "literal", what) }

  ** A parameter value, as an evaluator value, with its CdlClass conversion
  static PVal param(Obj? v, Str? convert, Str what) { make(v, convert, "param", what) }

  ** A value written as it is, never converted
  static PVal fixed(Obj? v) { p := make(v, null, "fixed", ""); p.written = v; return p }

  private new make(Obj? raw, Str? convert, Str role, Str what)
  {
    this.raw = raw
    this.convert = convert
    this.role = role
    this.what = what
  }

  Obj? raw
  Str? convert
  Str role
  Str what
  ** The SI unit of a number, where the generator recorded it
  Str? si
  ** The parameter whose declaration gave `si`, for a bound value
  Str? siFrom
  ** True for a temperature difference, false for an absolute temperature
  Bool? delta
  ** Never converted: a compound gain written in its numerator unit
  Bool unitFixed
  ** Written only when its unit group carries a unit (a PID's r)
  Bool onlyWithUnit
  ** The value written, set by the unit pass
  Obj? written

  ** A copy, for a copy of the comp that holds it
  PVal dup()
  {
    p := make(raw, convert, role, what)
    p.si = si; p.siFrom = siFrom; p.delta = delta; p.unitFixed = unitFixed; p.onlyWithUnit = onlyWithUnit; p.written = written
    return p
  }

  ** The value as the evaluator sees it
  Obj? envVal()
  {
    v := unwrap(raw)
    if (v is Duration) return ((Duration)v).ticks.toFloat / 1e9f
    return Values.toEnv(v)
  }

  ** A status value's value
  static Obj? unwrap(Obj? v)
  {
    if (v is StatusNumber) return ((StatusNumber)v).num
    if (v is StatusBool) return ((StatusBool)v).bool
    return v
  }
}

**
** How a comp carries units: slot groups that share one unit, an arithmetic
** op from inputs to an output, and slots with a fixed unit
**
internal class UnitRule
{
  new make(Str[][] keep, Str? op, Str[] ins, Str? out, Str:Str seeds)
  {
    this.keep = keep; this.op = op; this.ins = ins; this.out = out; this.seeds = seeds
  }
  Str[][] keep
  Str? op
  Str[] ins
  Str? out
  Str:Str seeds
  static UnitRule none() { make(Str[][,], null, Str[,], null, Str:Str[:]) }
}
