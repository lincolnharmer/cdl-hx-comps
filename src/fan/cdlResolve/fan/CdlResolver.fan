//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Resolves one configured CDL composite into one flat hx.comps comp graph.
**
** Given a namespace holding `hx.comps`, `kw.cdl` and the G36 libraries,
** the qname of a composite and its parameter values, `resolve` returns
** the graph as `sys.comp` data: one `hx.comps::Folder` whose children are
** hx.comps comps, each named by its CDL instance path, with every
** expression replaced by a value, every absent conditional child dropped,
** every array expanded and no nested composite left. Each input connector
** of the composite becomes a point input comp and each output connector a
** point output comp, so binding to a building is a separate step.
**
** Options:
**   - `pointUnits`: Dict of input or output connector (CDL name) to the
**     unit of the point bound to it, as a Str symbol or a Unit. Each unit
**     group a point unit reaches is resolved in that unit, and every
**     literal and parameter value in it is converted. With none, every
**     value stays SI.
**   - `id`: the root id and the prefix of every comp id (default `cdl`)
**
** Every refusal raises `CdlResolveErr`, naming the parameter, expression,
** child, connector or unit group. The resolver never guesses.
**
class CdlResolver
{
  ** Construct for a namespace that holds the CDL libraries
  new make(Namespace ns) { this.ns = ns }

  ** The namespace resolved against
  Namespace ns { private set }

  ** Resolve the composite `qname` with the CDL parameter values `params`
  ** into a flat comp graph as `sys.comp` data
  Dict resolve(Str qname, Dict params, Dict? opts := null)
  {
    spec := ns.spec(qname, false) ?: throw CdlResolveErr("$qname is not in the namespace")
    return resolveSpec(spec, params, opts)
  }

  ** Resolve a composite spec, as `resolve` does a qname
  Dict resolveSpec(Spec spec, Dict params, Dict? opts := null)
  {
    Resolution(CdlLib(ns), spec, params, opts ?: Etc.dict0).run
  }

  ** The graph as Xeto instance text, which `CompSpace.loadXeto` loads
  ** keeping every comp id
  static Str toXeto(Namespace ns, Dict graph)
  {
    ns.io.writeXetoToStr(graph)
  }
}

**
** One run of the resolver
**
internal class Resolution
{
  new make(CdlLib lib, Spec spec, Dict params, Dict opts)
  {
    this.lib = lib
    this.ns = lib.ns
    this.spec = spec
    this.qname = spec.qname
    this.params = params
    this.opts = opts
    this.rootId = opts["id"]?.toStr ?: "cdl"
    if (!Ref.isId(rootId) || rootId.contains(".")) throw CdlResolveErr("option id '$rootId' is not a valid id")
  }

  CdlLib lib
  Namespace ns
  Spec spec
  Str qname
  Dict params
  Dict opts
  Str rootId
  Inst? root
  FlatGraph flat := FlatGraph()
  Str:Sig rootIn := [:]
  Str:[Str:Sig] arrayOuts := [:]
  Inst[] insts := [,]

  Dict run()
  {
    if (!spec.slots.list.any { it.meta.has("cdlInstance") })
      throw CdlResolveErr("$qname is not a CDL composite: it has no cdlInstance children")
    label := spec.name

    // 1. parameters and bounds
    pe := ParamEnv(lib, spec, label)
    env := pe.eval(pe.fromGiven(params))
    pe.checkBounds(env)

    // 2-4. conditions, bindings and arrays, building the instance tree
    root = Inst(InstKind.composite, "", "", spec, spec, null)
    root.env = env
    root.exempt = pe.exempt
    initDeltaFacts(root)
    buildComposite(root)

    // 6. flatten: point inputs, then every comp with its links
    makeRootInputs
    insts.each |x|
    {
      if (x.kind == InstKind.comp) makeComp(x)
      else if (x.kind == InstKind.feed) makeFeed(x)
    }
    insts.each |x| { if (x.kind == InstKind.array) arrayOut(x, null) }
    makeRootOutputs

    // 5. units, then 7 is part of makeComp (Pre seeds)
    UnitPass(lib, flat, pointUnits).run

    return flat.emit(ns, rootId, spec)
  }

  ** The point units the caller gave, by connector CDL name
  once Str:Unit pointUnits()
  {
    acc := Str:Unit[:]
    pu := opts["pointUnits"] as Dict
    if (pu == null) return acc
    pu.each |v, n|
    {
      s := root.type.slots.list.find { (it.meta.has("cdlInput") || it.meta.has("cdlOutput")) && ParamEnv.cdlName(it) == n }
      if (s == null) throw CdlResolveErr("pointUnits: $n is not an input or output connector of $qname")
      if (root.gone[s.name] == true) throw CdlResolveErr("pointUnits: connector $n is removed by its condition (" + s.meta["cdlCondition"] + ") in this configuration")
      u := v is Unit ? (Unit)v : Unit.fromStr(v.toStr, false)
      if (u == null) throw CdlResolveErr("pointUnits: $n names unit '$v', which the unit database lacks")
      acc[n] = u
    }
    return acc
  }

//////////////////////////////////////////////////////////////////////////
// Tree
//////////////////////////////////////////////////////////////////////////

  private Bool evalBool(Str expr, Str:Obj? env, Str what)
  {
    Obj? v
    try v = Expression.eval(expr, env, lib.dottedFunc)
    catch (CdlResolveErr e) throw CdlResolveErr("$what: $e.msg")
    if (v isnot Bool) throw CdlResolveErr("$what: '$expr' gives ${Values.show(v)}, not a Boolean")
    return v
  }

  ** Conditions, bindings and children of one composite
  private Void buildComposite(Inst c)
  {
    where := c.isRoot ? c.type.name : c.path
    c.type.slots.each |s|
    {
      m := s.meta
      if (!m.has("cdlInput") && !m.has("cdlOutput")) return
      cond := m["cdlCondition"] as Str
      if (cond != null && !evalBool(cond, c.env, "$where: the condition of connector $s.name")) c.gone[s.name] = true
    }
    feeds := Spec[,]
    c.type.slots.each |s|
    {
      m := s.meta
      if (!m.has("cdlInstance") && !m.has("cdlFeed")) return
      cond := m["cdlCondition"] as Str
      if (cond != null && !evalBool(cond, c.env, "$where: the condition of child $s.name")) { c.gone[s.name] = true; return }
      if (m.has("cdlFeed")) { feeds.add(s); return }
      addChild(c, s)
    }
    // feeds after their targets, so a feed of a removed child goes with it
    feeds.each |s|
    {
      target := s.meta["cdlFeed"].toStr.split('.').first
      if (c.gone[target] == true) { c.gone[s.name] = true; return }
      addChild(c, s)
    }
  }

  private Void addChild(Inst c, Spec s)
  {
    where := c.isRoot ? c.type.name : c.path
    cls := lib.classOf(s)
    kind := classify(s, cls)
    // bindings evaluate in the parent's scope
    binds := Str:Obj?[:]
    deltas := Str:Bool[:]
    units := Str:Str[:]
    unitsFrom := Str:Str[:]
    bindDict := s.meta["cdlBind"] as Dict
    bindDict?.each |expr, key|
    {
      Obj? v
      try v = Expression.eval(expr.toStr, c.env, lib.dottedFunc)
      catch (CdlResolveErr e)
      {
        off := Expression.names(expr.toStr).find |n| { c.exempt[n] != null }
        if (off != null) throw CdlResolveErr("$where: the binding ${s.name}.$key = $expr reads $off, which has no value because its enable condition (" + c.exempt[off] + ") is false")
        throw CdlResolveErr("$where: the binding ${s.name}.$key = $expr: $e.msg")
      }
      binds[key] = v
      src := boundParam(expr.toStr)
      if (src != null)
      {
        if (c.deltaFacts[src] != null) deltas[key] = c.deltaFacts[src]
        if (c.unitFacts[src] != null) { units[key] = c.unitFacts[src]; unitsFrom[key] = c.unitFrom[src] ?: src }
      }
    }
    sizeExpr := s.meta["cdlArraySize"] as Str
    if (sizeExpr == null)
    {
      makeChild(c, s, kind, cls, s.name, null, binds, deltas, units, unitsFrom)
      return
    }
    sizeExpr = ParamEnv.stripParens(sizeExpr)
    n := ParamEnv(lib, c.type, where).count(sizeExpr, c.env, "$where: child ${s.name}[$sizeExpr]")
    if (kind == InstKind.composite) throw CdlResolveErr("$where: child ${s.name} is a vectorized composite, which the resolver does not expand")
    c.vec[s.name] = n
    for (k := 1; k <= n; ++k)
    {
      bk := Str:Obj?[:]
      binds.each |v, key|
      {
        list := v as List
        // a list one dimension deeper than the parameter distributes along the first
        if (list != null && paramDims(s, cls, key) + 1 == Values.shapeOf(v).size)
        {
          if (list.size != n) throw CdlResolveErr("$where: the binding ${s.name}.$key has ${list.size} elements; ${s.name}[$sizeExpr] has $n")
          bk[key] = list[k-1]
        }
        else bk[key] = v
      }
      makeChild(c, s, kind, cls, "${s.name}[$k]", k, bk, deltas, units, unitsFrom)
    }
  }

  private Int paramDims(Spec s, Dict? cls, Str key)
  {
    p := s.type.slot(key, false)
    size := p?.meta?.get("cdlArraySize") as Str
    if (size == null) return 0
    return ParamEnv.splitTop(ParamEnv.stripParens(size)).size
  }

  private InstKind classify(Spec s, Dict? cls)
  {
    if (s.meta.has("cdlFeed")) return InstKind.feed
    if (cls == null)
    {
      if (s.type.slots.list.any { it.meta.has("cdlInstance") }) return InstKind.composite
      throw CdlResolveErr("child ${s.name} (${s.type.qname}) has no cdlOf and is not a composite")
    }
    switch (cls["grade"]?.toStr)
    {
      case "array":     return InstKind.array
      case "composite": return InstKind.composite
      case "link":      return InstKind.wire
    }
    if (!s.type.isComp) throw CdlResolveErr("child ${s.name}: ${s.type.qname} is not a comp")
    return InstKind.comp
  }

  private Void makeChild(Inst c, Spec s, InstKind kind, Dict? cls, Str name, Int? index, Str:Obj? binds, Str:Bool deltas, Str:Str units, Str:Str unitsFrom)
  {
    path := c.isRoot ? name : "${c.path}.$name"
    cdl := (s.meta["cdlName"]?.toStr ?: s.name) + (index == null ? "" : "[$index]")
    cdlPath := c.isRoot ? cdl : "${c.cdlPath}.$cdl"
    x := Inst(kind, path, cdlPath, s, s.type, c)
    x.index = index
    x.cls = cls
    c.kids[name] = x
    insts.add(x)
    switch (kind)
    {
      case InstKind.composite:
        given := Str:Obj?[:]
        binds.each |v, key|
        {
          p := s.type.slot(key, false)
          if (p == null || !p.meta.has("cdlParam")) throw CdlResolveErr("${c.isRoot ? c.type.name : c.path}: the binding ${s.name}.$key is not a parameter of ${s.type.qname}")
          given[ParamEnv.cdlName(p)] = v
        }
        pe := ParamEnv(lib, s.type, path)
        x.env = pe.eval(given)
        pe.checkBounds(x.env)
        x.exempt = pe.exempt
        initDeltaFacts(x)
        deltas.each |d, key| { p := s.type.slot(key); x.deltaFacts[ParamEnv.cdlName(p)] = d }
        units.each |u, key|
        {
          p := s.type.slot(key)
          n := ParamEnv.cdlName(p)
          if (x.unitFacts[n] != null) return
          x.unitFacts[n] = u
          x.unitFrom[n] = unitsFrom[key]
        }
        buildComposite(x)
      case InstKind.array:
        given := Str:Obj?[:]
        binds.each |v, key|
        {
          p := s.type.slot(key, false)
          if (p == null || !p.meta.has("cdlParam")) throw CdlResolveErr("$path: the binding $key is not a parameter of ${s.type.qname}")
          given[ParamEnv.cdlName(p)] = v
        }
        pe := ParamEnv(lib, s.type, path)
        x.env = pe.eval(given)
        pe.checkBounds(x.env)
      case InstKind.comp:
        x.env = binds
        x.deltaFacts = deltas
        x.unitFacts = units
        x.unitFrom = unitsFrom
        checkClassBinds(x)
      default:
        x.env = binds
        x.deltaFacts = deltas
    }
  }

  ** Every binding of an elementary child must name a parameter its class
  ** maps, and satisfy the bounds the class declares
  private Void checkClassBinds(Inst x)
  {
    cls := x.cls
    params := cls["params"] as Dict ?: Etc.dict0
    feeds := cls["feeds"] as Dict ?: Etc.dict0
    bounds := cls["bounds"] as Dict ?: Etc.dict0
    x.env.each |v, key|
    {
      if (!params.has(key) && !feeds.has(key))
        throw CdlResolveErr("${x.path}: the binding $key is not a parameter " + cls["cdlClass"] + " maps to ${x.type.qname}")
      b := bounds[key] as Dict
      if (b == null) return
      f := v as Float
      if (f == null) return
      Obj? loRaw := b["minVal"] ?: b["cdlMin"]
      Obj? hiRaw := b["maxVal"] ?: b["cdlMax"]
      lo := loRaw == null ? null : Float.fromStr(loRaw.toStr, false)
      hi := hiRaw == null ? null : Float.fromStr(hiRaw.toStr, false)
      if (lo != null && f < lo) throw CdlResolveErr("${x.path}: parameter $key = ${Values.show(f)} is below the minimum ${Values.show(lo)} of " + cls["cdlClass"] + "")
      if (hi != null && f > hi) throw CdlResolveErr("${x.path}: parameter $key = ${Values.show(f)} is above the maximum ${Values.show(hi)} of " + cls["cdlClass"] + "")
    }
  }

  ** The temperature kind of each parameter of a composite its declaration
  ** states: true for a difference, false for an absolute temperature
  private Void initDeltaFacts(Inst c)
  {
    c.type.slots.each |s|
    {
      if (!s.meta.has("cdlParam")) return
      d := declaredDelta(s)
      if (d != null) c.deltaFacts[ParamEnv.cdlName(s)] = d
      u := ParamEnv.siUnitOf(s)
      if (u == null) return
      n := ParamEnv.cdlName(s)
      c.unitFacts[n] = u
      c.unitFrom[n] = c.isRoot ? n : "${c.path}.$n"
    }
  }

  static Bool? declaredDelta(Spec? s)
  {
    if (s == null) return null
    if (ParamEnv.isDelta(s)) return true
    if (s.meta["quantity"]?.toStr == "temperature" || s.meta["cdlQuantityKind"] == "ThermodynamicTemperature") return false
    return null
  }

  ** The parameter whose unit and temperature kind a binding passes on,
  ** where the expression is that one parameter, scaled by a number or
  ** negated: `dTHys`, `0.5*dTHys`, `-THys`; else null
  private Str? boundParam(Str expr)
  {
    names := Expression.names(expr)
    if (names.size != 1 || names.first.contains(".")) return null
    return scaledName.matcher(expr).matches ? names.first : null
  }

  private static const Regex scaledName := Regex<|^\s*-?\s*(\d+\.?\d*(?:[eE][-+]?\d+)?\s*\*\s*)?[A-Za-z_][A-Za-z0-9_]*(\s*[*/]\s*\d+\.?\d*(?:[eE][-+]?\d+)?)?\s*$|>

//////////////////////////////////////////////////////////////////////////
// Drivers
//////////////////////////////////////////////////////////////////////////

  ** The driver of a sink: its `link`, or the one of its `cdlAltLink`
  ** alternatives that is present. Null when it has neither.
  private Str? chooseDriver(Inst c, Dict meta, Str what)
  {
    link := meta["link"] as Str
    alt := meta["cdlAltLink"] as Str
    if (alt == null) return link
    cands := alt.split(',').findAll { !it.isEmpty }
    if (link != null && !cands.contains(link)) cands.insert(0, link)
    present := cands.findAll { isPresent(c, it) }
    if (present.size == 1) return present.first
    if (present.isEmpty) throw CdlResolveErr("$what: none of its alternative drivers is present (" + cands.join(", ") + ")")
    throw CdlResolveErr("$what: more than one of its alternative drivers is present (" + present.join(", ") + ")")
  }

  private Bool isPresent(Inst c, Str path)
  {
    parts := path.split('.')
    if (parts.size == 1)
    {
      s := c.type.slot(parts[0], false)
      return s != null && c.gone[parts[0]] != true
    }
    a := parts[0]
    if (c.vec[a] != null) return true
    kid := c.kids[a]
    if (kid == null) return false
    if (kid.kind == InstKind.composite) return kid.gone[parts[1]] != true
    return true
  }

  ** Resolve a link path in composite `c` to the endpoints that drive it,
  ** walking through composite connectors. Null when the driver is absent.
  private Sig? resolveIn(Inst c, Str path, Str what)
  {
    parts := path.split('.')
    if (parts.size == 1)
    {
      n := parts[0]
      if (c.gone[n] == true) return null
      if (c.isRoot)
      {
        sig := rootIn[n]
        if (sig == null)
        {
          s := c.type.slot(n, false)
          if (s == null) throw CdlResolveErr("$what: $n is not a connector of ${c.type.qname}")
          if (s.meta.has("cdlOutput")) throw CdlResolveErr("$what: reads the output connector $n of the root")
          throw CdlResolveErr("$what: $n is not an input connector")
        }
        return sig.copyFacts(Sig(sig.eps, sig.shape))
      }
      if (c.index != null) throw CdlResolveErr("$what: ${c.path} is a vectorized composite")
      conn := c.type.slot(n, false) ?: throw CdlResolveErr("$what: $n is not a connector of ${c.type.qname}")
      if (!conn.meta.has("cdlInput")) throw CdlResolveErr("$what: reads ${c.path}.$n, which is not an input connector")
      p := c.parent
      sub := c.slot.slotOwn(n, false)
      // CDL connects every input: a present input nothing drives refuses
      if (sub == null) throw CdlResolveErr("$what: reads the input connector ${c.path}.$n, which nothing drives")
      drv := chooseDriver(p, sub.metaOwn, "${c.path}.$n")
      if (drv == null) throw CdlResolveErr("$what: reads the input connector ${c.path}.$n, which nothing drives")
      sig := resolveIn(p, drv, "${c.path}.$n")
      if (sig == null) return null
      if (sub.metaOwn.has("loopCut")) sig.cut = true
      seedVia(p, sub.metaOwn, sig)
      addFacts(sig, c.type.slot(n, false))
      return sig
    }
    if (parts.size != 2) throw CdlResolveErr("$what: link path $path is neither a connector nor child.slot")
    a := parts[0]; b := parts[1]
    n := c.vec[a]
    if (n != null)
    {
      eps := Ep[,]
      Int[]? sub
      Sig? last
      for (k := 1; k <= n; ++k)
      {
        sig := scalarOut(c.kids["${a}[$k]"], b, what)
        if (sig == null) return null
        if (sub == null) sub = sig.shape
        else if (!Sig.same(sub, sig.shape)) throw CdlResolveErr("$what: ${a}.$b has shape $sub on one element and ${sig.shape} on another")
        eps.addAll(sig.eps)
        last = sig
      }
      res := Sig(eps, [n].addAll(sub ?: Int[,]))
      if (last != null) { res.cut = last.cut; res.units = last.units; res.deltas = last.deltas }
      return res
    }
    kid := c.kids[a]
    if (kid == null)
    {
      if (c.gone[a] == true) return null
      throw CdlResolveErr("$what: ${c.isRoot ? c.type.name : c.path} has no child $a")
    }
    return scalarOut(kid, b, what)
  }

  private Sig? scalarOut(Inst kid, Str b, Str what)
  {
    switch (kid.kind)
    {
      case InstKind.comp:
      case InstKind.feed:
        if (kid.type.slot(b, false) == null) throw CdlResolveErr("$what: ${kid.path} (${kid.type.qname}) has no slot $b")
        return Sig([Ep(kid.flatName, b)], Int[,])
      case InstKind.composite:
        if (kid.gone[b] == true) return null
        os := kid.type.slot(b, false) ?: throw CdlResolveErr("$what: ${kid.path} has no connector $b")
        if (!os.meta.has("cdlOutput")) throw CdlResolveErr("$what: reads ${kid.path}.$b, which is not an output connector")
        drv := chooseDriver(kid, os.meta, "${kid.path}.$b")
        if (drv == null) return null
        sig := resolveIn(kid, drv, "${kid.path}.$b")
        if (sig == null) return null
        if (os.metaOwn.has("loopCut")) sig.cut = true
        addFacts(sig, os)
        return sig
      case InstKind.array:
        return arrayOut(kid, b)
      default:
        throw CdlResolveErr("$what: reads ${kid.path}, a " + kid.cls?.get("cdlClass") + " link record, which carries no value of its own")
    }
  }

  ** True when a link runs through Conversions.IntegerToReal, whose output
  ** CDL seeds as dimensionless: the record is gone once flattened, so its
  ** seed moves onto the sink
  private Bool viaIntToReal(Inst c, Dict meta)
  {
    via := meta["cdlLinkVia"] as Str
    if (via == null) return false
    return via.split(',').any |w|
    {
      wire := c.kids[w] ?: c.kids["${w}[1]"]
      return wire?.cls?.get("cdlClass") == "Buildings.Controls.OBC.CDL.Conversions.IntegerToReal"
    }
  }

  ** A Logical.Pre the link runs through gives its target a starting value
  private Void seedVia(Inst c, Dict meta, Sig sig)
  {
    via := meta["cdlLinkVia"] as Str
    if (via == null) return
    via.split(',').each |w|
    {
      wire := c.kids[w]
      if (wire == null || wire.cls?.get("cdlClass") != "Buildings.Controls.OBC.CDL.Logical.Pre") return
      v := wire.env["pre_u_start"] ?: false
      if (v isnot Bool) throw CdlResolveErr("${wire.path}: pre_u_start is ${Values.show(v)}, not a Boolean")
      sig.seed = v
    }
  }

  private Void addFacts(Sig sig, Spec? conn)
  {
    if (conn == null) return
    u := ParamEnv.siUnitOf(conn)
    if (u != null) sig.units.add(u)
    d := declaredDelta(conn)
    if (d != null) sig.deltas.add(d)
  }

  ** The driver of a sink slot of an elementary child, sliced to its
  ** element where the child is vectorized
  private Sig? sinkSig(Inst x, Spec sub, Str what)
  {
    c := x.parent
    drv := chooseDriver(c, sub.metaOwn, what)
    if (drv == null) return null
    sig := resolveIn(c, drv, what)
    if (sig == null) return null
    if (sub.metaOwn.has("loopCut")) sig.cut = true
    seedVia(c, sub.metaOwn, sig)
    if (x.index == null)
    {
      if (!sig.isScalar) throw CdlResolveErr("$what: driven by $drv, which has shape ${sig.shape}")
      return sig
    }
    n := c.vec[x.slot.name]
    if (sig.shape.isEmpty || sig.shape.first != n)
      throw CdlResolveErr("$what: ${x.slot.name}[$n] is driven by $drv, which has shape ${sig.shape}")
    el := sig.elem(x.index)
    if (!el.isScalar) throw CdlResolveErr("$what: element ${x.index} of its driver $drv has shape ${el.shape}")
    return el
  }

//////////////////////////////////////////////////////////////////////////
// Flat comps
//////////////////////////////////////////////////////////////////////////

  ** One point input comp per present input connector, one per element of
  ** an array connector
  private Void makeRootInputs()
  {
    root.type.slots.each |s|
    {
      if (!s.meta.has("cdlInput") || root.gone[s.name] == true) return
      sh := connShape(root, s)
      names := FlatGraph.elemNames(s.name, sh)
      cdls := FlatGraph.cdlElemNames(ParamEnv.cdlName(s), sh)
      eps := Ep[,]
      names.each |nm, i|
      {
        fc := flat.add(nm, nm, cdls[i], ns.spec(isBool(s) ? "hx.comps::BoolPointInput" : "hx.comps::NumberPointInput"), null, "input")
        connMeta(fc, s, "curVal")
        eps.add(Ep(fc.name, "curVal"))
      }
      sig := Sig(eps, sh)
      addFacts(sig, s)
      rootIn[s.name] = sig
    }
  }

  private Bool isBool(Spec s) { s.meta["cdlType"] == "Boolean" || s.type.qname == "hx.comps::StatusBool" }

  private Int[] connShape(Inst c, Spec s)
  {
    size := s.meta["cdlArraySize"] as Str
    if (size == null) return Int[,]
    size = ParamEnv.stripParens(size)
    return ParamEnv(lib, c.type, c.type.name).shape(size, c.env, "connector ${s.name}")
  }

  private Void connMeta(FlatComp fc, Spec s, Str slot)
  {
    fc.extra["cdlName"] = ParamEnv.cdlName(s)
    si := ParamEnv.siUnitOf(s)
    if (si != null) { fc.extra["cdlUnit"] = si; fc.siSeeds[slot] = si }
    d := declaredDelta(s)
    if (d != null) fc.kindSeeds[slot] = d
    u := pointUnits[ParamEnv.cdlName(s)]
    if (u != null)
    {
      fc.extra["pointUnit"] = u.symbol
      fc.pointUnit = u
      fc.pointSlot = slot
    }
    spec := pointSpec(s)
    if (spec != null) fc.vals["bindSpec"] = PVal.fixed(spec)
    scope := s.meta["cdlPointScope"]
    if (scope != null) fc.extra["cdlPointScope"] = scope
    pu := s.meta["cdlPointUnit"]
    if (pu != null) fc.extra["cdlPointUnit"] = pu
    ps := s.meta["cdlPointScale"]
    if (ps != null) fc.extra["cdlPointScale"] = ps
    fc.conn = s
  }

  ** The point spec of a connector: cdlPointSpec, or the case of
  ** cdlPointSpecCases whose condition holds
  private Ref? pointSpec(Spec s)
  {
    spec := s.meta["cdlPointSpec"] as Ref
    if (spec != null) return spec
    cases := s.meta["cdlPointSpecCases"] as List
    if (cases == null) return null
    hit := cases.findAll |Dict d->Bool| { evalBool(d["when"].toStr, root.env, "connector ${s.name}: a point spec case") }
    if (hit.size > 1) throw CdlResolveErr("connector ${s.name}: more than one point spec case holds")
    return (hit.first as Dict)?.get("pointSpec") as Ref
  }

  ** One point output comp per present output connector
  private Void makeRootOutputs()
  {
    root.type.slots.each |s|
    {
      if (!s.meta.has("cdlOutput") || root.gone[s.name] == true) return
      what := "output connector ${s.name}"
      drv := chooseDriver(root, s.meta, what) ?: throw CdlResolveErr("$what: nothing drives it")
      sig := resolveIn(root, drv, what) ?: throw CdlResolveErr("$what: its driver $drv is absent in this configuration")
      sh := connShape(root, s)
      if (!Sig.same(sig.shape, sh)) throw CdlResolveErr("$what: has shape $sh and is driven by $drv with shape ${sig.shape}")
      names := FlatGraph.elemNames(s.name, sh)
      cdls := FlatGraph.cdlElemNames(ParamEnv.cdlName(s), sh)
      names.each |nm, i|
      {
        fc := flat.add(nm, nm, cdls[i], ns.spec(isBool(s) ? "hx.comps::BoolPointOutput" : "hx.comps::NumberPointOutput"), null, "output")
        connMeta(fc, s, "in")
        fc.links["in"] = FlatLink(sig.eps[i], sig.cut)
      }
    }
  }

  ** The literal values the generator wrote on a child's own slots
  private Void literals(FlatComp fc, Inst x)
  {
    units := x.slot.meta["cdlLiteralUnits"] as Dict ?: Etc.dict0
    deltas := (x.slot.meta["cdlLiteralDelta"] as Str ?: "").split(',')
    x.slot.slotsOwn.each |ss|
    {
      m := ss.metaOwn
      if (m.has("link") || m.has("cdlAltLink")) return
      if (!m.has("val") && ss.slotsOwn.isEmpty) return
      pv := PVal.literal(ns.instantiate(ss), "${x.path}.${ss.name}")
      pv.si = units[ss.name]?.toStr
      // a literal marked a difference is one; any other takes its kind group's
      if (deltas.contains(ss.name)) pv.delta = true
      fc.vals[ss.name] = pv
    }
  }

  ** The links of a child's own slots
  private Void links(FlatComp fc, Inst x)
  {
    x.slot.slotsOwn.each |ss|
    {
      m := ss.metaOwn
      if (!m.has("link") && !m.has("cdlAltLink")) return
      what := "${x.path}.${ss.name}"
      sig := sinkSig(x, ss, what)
      if (sig == null) return
      fc.links[ss.name] = FlatLink(sig.eps.first, sig.cut)
      if (viaIntToReal(x.parent, m)) fc.siSeeds[ss.name] = "1"
      if (sig.seed != null)
      {
        pv := PVal.literal(isStatusBool(fc, ss.name) ? StatusBool(sig.seed, Status.ok) : sig.seed, what)
        pv.role = "seed"
        fc.vals[ss.name] = pv
        fc.extra["cdlPreSeed"] = ss.name
      }
      // every connector on the way states its unit and kind; all of them seed
      fc.siFacts[ss.name] = sig.units.dup
      fc.kindFacts[ss.name] = sig.deltas.dup
    }
  }

  private Bool isStatusBool(FlatComp fc, Str slot) { fc.spec.slot(slot, false)?.type?.qname == "hx.comps::StatusBool" }

  ** One elementary child as one comp
  private Void makeComp(Inst x)
  {
    cls := x.cls
    fc := flat.add(x.flatName, x.path, x.cdlPath, x.type, cls, "comp")
    fc.compound = compoundUnit(x.slot)
    fc.compoundMeta = x.slot.meta["cdlCompoundGain"] as Dict
    connUnits := x.slot.meta["cdlConnUnits"] as Dict
    literals(fc, x)
    links(fc, x)
    params := cls["params"] as Dict ?: Etc.dict0
    conv := cls["convert"] as Dict ?: Etc.dict0
    conns := cls["connectors"] as Dict ?: Etc.dict0
    connUnits?.each |u, n|
    {
      slot := conns[n] ?: params[n]
      if (slot != null) fc.siSeeds[slot.toStr] = u.toStr
    }
    // bound parameters onto their slots; a fed parameter goes to its feed
    x.env.each |v, key|
    {
      slot := params[key]?.toStr
      if (slot == null) return
      pv := PVal.param(v, conv[key]?.toStr, "${x.path}.$key")
      pv.delta = x.deltaFacts[key]
      pv.si = x.unitFacts[key]
      pv.siFrom = x.unitFrom[key]
      fc.vals[slot] = pv
    }
    // fixed slot values the class always writes
    (cls["fixed"] as Dict)?.each |v, slot|
    {
      if (fc.vals[slot] != null) return
      // the class records a fixed value as text: decode it as the slot's type
      ss := x.type.slot(slot, false) ?: throw CdlResolveErr("${x.path}: the fixed slot $slot is not on ${x.type.qname}")
      if (v is Str && ss.type.qname != "sys::Str") v = ss.type.binding.decodeScalar(v.toStr)
      fc.vals[slot] = PVal.literal(v, "${x.path}.$slot")
    }
    // CDL defaults of mapped parameters left unbound
    (cls["cdlDefaults"] as Dict)?.each |expr, key|
    {
      slot := params[key]?.toStr
      if (slot == null || x.env.containsKey(key) || fc.vals[slot] != null) return
      v := Expression.eval(expr.toStr, classEnv(x, fc), lib.dottedFunc)
      fc.vals[slot] = PVal.param(v, conv[key]?.toStr, "${x.path}.$key (CDL default $expr)")
    }
    // parameters written whenever their unit group carries a unit
    (cls["writeWhenUnit"] as Str ?: "").split(',').each |key|
    {
      if (key.isEmpty) return
      slot := params[key]?.toStr ?: throw CdlResolveErr("" + cls["cdlClass"] + ": writeWhenUnit names $key, which it does not map")
      if (fc.vals[slot] != null) return
      v := Values.toEnv(ns.instantiate(x.type.slot(slot)))
      pv := PVal.param(v, conv[key]?.toStr, "${x.path}.$key (CDL default, written as its unit group carries a unit)")
      pv.onlyWithUnit = true
      fc.vals[slot] = pv
    }
    // a numeric parameter left at the comp's default is written whenever its
    // unit group carries a unit, so a unitless default is never read in a
    // point unit (UnitDelay's y_start 0 is 0 K, not 0 °F)
    params.each |slotObj, key|
    {
      slot := slotObj.toStr
      if (fc.vals[slot] != null) return
      ss := x.type.slot(slot, false)
      t := ss?.type?.qname
      if (t != "sys::Number" && t != "hx.comps::StatusNumber") return
      d := PVal.unwrap(ns.instantiate(ss)) as Number
      if (d == null) return
      pv := PVal.param(d.toFloat, conv[key]?.toStr, "${x.path}.$key (comp default, written as its unit group carries a unit)")
      pv.onlyWithUnit = true
      fc.vals[slot] = pv
    }
    // an input CDL always links
    (cls["linkAlways"] as Dict)?.each |v, key|
    {
      slot := conns[key]?.toStr
      if (slot != null && fc.links[slot] == null) throw CdlResolveErr("${x.path}: " + cls["cdlClass"] + " needs its input $key linked, and nothing links it")
    }
  }

  ** The CDL parameter values an elementary child has, for its CDL defaults
  private Str:Obj? classEnv(Inst x, FlatComp fc)
  {
    env := Str:Obj?[:]
    params := x.cls["params"] as Dict ?: Etc.dict0
    names := x.cls["cdlNames"] as Dict ?: Etc.dict0
    params.each |slot, key|
    {
      Obj? v := x.env[key]
      if (v == null && fc.vals[slot.toStr] != null) v = fc.vals[slot.toStr].envVal
      if (v == null) v = Values.toEnv(PVal.unwrap(ns.instantiate(x.type.slot(slot.toStr))))
      env[key] = v
      exact := names[key]
      if (exact != null) env[exact.toStr] = v
    }
    return env
  }

  ** The gain unit of a child run on its class's compound gain comp (s/K),
  ** from `cdlCompoundGain` as a Str or as a Dict with `unit`
  static Str? compoundUnit(Spec slot)
  {
    m := slot.meta["cdlCompoundGain"]
    if (m == null) return null
    if (m is Dict) return ((Dict)m)["unit"]?.toStr ?: throw CdlResolveErr("child ${slot.name}: cdlCompoundGain names no unit")
    return m.toStr
  }

  ** One feed comp, its value taken from the child it supplies
  private Void makeFeed(Inst x)
  {
    fc := flat.add(x.flatName, x.path, x.cdlPath, x.type, null, "feed")
    literals(fc, x)
    links(fc, x)
    fc.extra["cdlFeed"] = x.slot.meta["cdlFeed"]
    c := x.parent
    toks := x.slot.meta["cdlFeed"].toStr.split('.')
    targetName := x.index == null ? toks[0] : "${toks[0]}[$x.index]"
    key := toks[1]
    target := c.kids[targetName] ?: throw CdlResolveErr("${x.path}: feeds ${targetName}, which is not a child")
    if (target.kind != InstKind.comp) throw CdlResolveErr("${x.path}: feeds ${target.path}, which is not a comp")
    feeds := target.cls["feeds"] as Dict ?: Etc.dict0
    feed := feeds[key] as Dict
    if (feed == null)
    {
      // a feed of a comp slot, not of a CDL parameter, carries its literal
      if (target.type.slot(key, false) != null && fc.vals["out"] != null) { fc.feedFor = Ep(target.flatName, key); return }
      throw CdlResolveErr("${x.path}: " + target.cls["cdlClass"] + " feeds no $key")
    }
    via := (feed["via"] as Ref)?.id
    if (via != "hx.comps::NumberConst" && via != "hx.comps::BoolConst") return
    Obj? v := target.env[key]
    if (v == null && fc.vals["out"] != null) return
    if (v == null)
    {
      expr := (target.cls["cdlDefaults"] as Dict)?.get(key)
      if (expr == null) throw CdlResolveErr("${x.path}: supplies ${target.path}.$key, which has no value, no literal and no CDL default")
      v = Expression.eval(expr.toStr, classEnv(target, flat.get(target.flatName) ?: fc), lib.dottedFunc)
    }
    pv := PVal.param(v, null, "${target.path}.$key")
    pv.delta = target.deltaFacts[key]
    pv.si = target.unitFacts[key]
    pv.siFrom = target.unitFrom[key]
    cu := compoundUnit(target.slot)
    if (cu != null)
    {
      // the gain of a compound unit is written in its numerator unit, never converted
      pv.si = cu.split('/').first
      pv.unitFixed = true
    }
    fc.vals["out"] = pv
    fc.feedFor = Ep(target.flatName, feed["slot"].toStr)
  }

//////////////////////////////////////////////////////////////////////////
// Arrays
//////////////////////////////////////////////////////////////////////////

  ** The signal an array instance's output connector gives, expanding the
  ** instance on first use. A null `conn` only expands it.
  private Sig? arrayOut(Inst a, Str? conn)
  {
    outs := arrayOuts[a.path]
    if (outs == null)
    {
      outs = ArrayExpand(this, a).run
      arrayOuts[a.path] = outs
    }
    if (conn == null) return null
    sig := outs[conn] ?: throw CdlResolveErr("${a.path}: ${a.type.qname} has no output $conn")
    // a copy, so one reader's cut or seed never reaches another
    return sig.copyFacts(Sig(sig.eps, sig.shape))
  }

  ** The driver of an array instance's input connector, with its shape
  internal Sig? arrayIn(Inst a, Str conn)
  {
    if (a.index != null) throw CdlResolveErr("${a.path}: a vectorized array class instance, which the resolver does not expand")
    sub := a.slot.slotOwn(conn, false)
    if (sub == null) return null
    what := "${a.path}.$conn"
    drv := chooseDriver(a.parent, sub.metaOwn, what)
    if (drv == null) return null
    sig := resolveIn(a.parent, drv, what)
    if (sig == null) return null
    if (sub.metaOwn.has("loopCut")) sig.cut = true
    seedVia(a.parent, sub.metaOwn, sig)
    return sig
  }

  internal FlatGraph flatGraph() { flat }
}
