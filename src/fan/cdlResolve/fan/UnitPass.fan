//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Gives every value written to a comp its unit, and converts it into the
** unit of the point its group reaches.
**
** A node is one slot of one flat comp. Two structures join nodes:
**   - the unit group: a link, a CdlClass `unitRule` keep group, and an
**     add, sub, sum or delta op join their slots, since hx.comps adds and
**     subtracts only values in one unit; a mul or div joins its output to
**     the input whose partner is dimensionless, and a div of two values in
**     one unit joins its inputs and makes its output dimensionless;
**   - the kind group (links and keep groups only), which says whether a
**     temperature is absolute or a difference: a sub of two absolute
**     temperatures gives a difference, and a delta op's output is one.
**
** Point units reach a unit group from the point comps of the root's
** connectors. Every value in a group with a point unit converts from SI
** into it: an absolute value with the offset, a difference by scale alone,
** and a PID's `r`, the scale of its control error, by scale. A PID's `k`
** is in no group and never converts. With no point unit a value is written
** in SI. A group with two point units, or a value it cannot convert, refuses
** naming the group.
**
internal class UnitPass
{
  new make(CdlLib lib, FlatGraph g, Str:Unit pointUnits)
  {
    this.lib = lib
    this.g = g
    this.pointUnits = pointUnits
  }

  CdlLib lib
  FlatGraph g
  Str:Unit pointUnits

  private Str:Str uparent := [:]
  private Str:Str kparent := [:]
  private Str:UnitRule rules := [:]
  private [Str:Str]? siOf
  private Str:Bool kindOf := [:]
  private Str:Bool kindConflict := [:]
  private Str:Unit dispOf := [:]
  private Str:Str derived := [:]
  ** Each constant's readers, by constant name
  private Str:Str[] reads := [:]

  Void run()
  {
    g.comps.each |fc| { rules[fc.name] = ruleOf(fc) }

    // links and keep groups join both structures; a link out of a constant
    // joins nothing yet, since one constant may feed several unit domains
    reads.ordered = true
    g.comps.each |fc|
    {
      fc.links.each |l, slot|
      {
        to := node(fc.name, slot)
        from := g.comps[l.from.comp]
        if (from != null && isConst(from)) { node(from.name, l.from.slot); reads.getOrAdd(from.name) |->Str[]| { Str[,] }.add(to); return }
        join(node(l.from.comp, l.from.slot), to, true)
      }
      r := rules[fc.name]
      r.keep.each |grp| { grp.eachRange(1..-1) |s| { join(node(fc.name, grp.first), node(fc.name, s), true) } }
      if (r.op == "add" || r.op == "sub" || r.op == "delta" || r.op == "sum")
        r.ins.each |s| { join(node(fc.name, s), node(fc.name, r.out), false) }
    }

    arithmetic
    siOf = collectSi
    ratios
    siOf = collectSi
    kinds
    points
    placeConsts(reads)
    products
    materialize
    pointUnitsShown
  }

  ** A literal constant: its value goes to every reader, in that reader's unit
  static Bool isConst(FlatComp fc)
  {
    fc.kind == "comp" && fc.cls?.get("grade")?.toStr == "const" && fc.spec.name == "NumberConst"
  }

//////////////////////////////////////////////////////////////////////////
// Products and quotients
//////////////////////////////////////////////////////////////////////////

  private static Bool real(Str? u) { u != null && u != "1" }

  private Bool joinU(Str x, Str y)
  {
    if (ufind(x) == ufind(y)) return false
    join(x, y, false)
    return true
  }

  private Bool derive(Str n, Str u)
  {
    if (derived[n] != null) return false
    derived[n] = u
    return true
  }

  **
  ** Units through a mul or div, forward from its inputs and backward from
  ** its output: a dimensionless factor passes the other's unit on; a
  ** quotient of two values in one unit is dimensionless, and a
  ** dimensionless quotient has its two inputs in one unit.
  **
  private Void arithmetic()
  {
    changed := true
    while (changed)
    {
      changed = false
      siOf = collectSi
      g.comps.each |fc|
      {
        r := rules[fc.name]
        if (r.op != "mul" && r.op != "div") return
        a := node(fc.name, r.ins[0]); b := node(fc.name, r.ins[1]); o := node(fc.name, r.out)
        ua := siOf[ufind(a)]; ub := siOf[ufind(b)]; uo := siOf[ufind(o)]
        step := false
        if (r.op == "mul")
        {
          if (ua == "1" && real(ub)) step = joinU(o, b) || step
          if (ub == "1" && real(ua)) step = joinU(o, a) || step
          if (ua == "1" && ub == "1") step = derive(o, "1") || step
          if (real(uo) && ua == uo) step = derive(b, "1") || step
          if (real(uo) && ub == uo) step = derive(a, "1") || step
          if (uo == "1" && ua == "1") step = derive(b, "1") || step
          if (uo == "1" && ub == "1") step = derive(a, "1") || step
          if (real(uo) && ua == "1") step = joinU(o, b) || step
          if (real(uo) && ub == "1") step = joinU(o, a) || step
        }
        else
        {
          if (ub == "1" && real(ua)) step = joinU(o, a) || step
          if (real(ua) && ua == ub) { step = joinU(a, b) || step; step = derive(o, "1") || step }
          if (ua == "1" && ub == "1") step = derive(o, "1") || step
          if (uo == "1" && (real(ua) || real(ub))) step = joinU(a, b) || step
          if (real(uo) && ua == uo) step = derive(b, "1") || step
          if (real(uo) && ub == "1") step = joinU(o, a) || step
          if (uo == "1" && ua == "1") step = derive(b, "1") || step
        }
        if (step) changed = true
      }
    }
  }

  ** A product or quotient of two values with units has no Haystack unit to
  ** convert into, so it may not touch a converted group
  private Void products()
  {
    g.comps.each |fc|
    {
      r := rules[fc.name]
      if (r.op != "mul" && r.op != "div") return
      a := node(fc.name, r.ins[0]); b := node(fc.name, r.ins[1]); o := node(fc.name, r.out)
      ra := ufind(a); rb := ufind(b); ro := ufind(o)
      if (dispOf[ra] == null && dispOf[rb] == null && dispOf[ro] == null) return
      ok := (ro == ra && siOf[rb] == "1") || (ro == rb && siOf[ra] == "1") || (r.op == "div" && ra == rb)
      // a ratio of two values in one unit holds under a change of scale, but
      // not of offset: two temperatures must both be differences
      if (ok && r.op == "div" && ra == rb && dispOf[ra] != null && Unit.fromStr(siOf[ra] ?: "", false)?.convertTo(0f, dispOf[ra]) != 0f)
      {
        if (kindOf[kfind(a)] != true || kindOf[kfind(b)] != true)
          throw CdlResolveErr("${fc.path} (${fc.spec.name}): a ratio of temperatures that are not both differences changes when converted to ${dispOf[ra].symbol}")
      }
      if (!ok) throw CdlResolveErr("${fc.path} (${fc.spec.name}): a ${r.op} of values in " + (siOf[ra] ?: "an unknown unit") + " and " + (siOf[rb] ?: "an unknown unit") + " touches a unit group converted to a point unit, and the result has no unit to convert into")
    }
  }

//////////////////////////////////////////////////////////////////////////
// Constants
//////////////////////////////////////////////////////////////////////////

  **
  ** Each constant joins the unit group of its readers. Readers in groups of
  ** different units or temperature kinds each get a copy of their own,
  ** named `<constant>_<n>`, so a 0 that feeds a loop signal and a
  ** temperature difference is 0 in each. A constant whose recorded unit
  ** differs from its group's refuses, unless its value is 0 in both.
  **
  private Void placeConsts(Str:Str[] reads)
  {
    reads.each |readers, name|
    {
      c := g.comps[name]
      Str:Str[] byKey := [:]
      byKey.ordered = true
      readers.each |rn|
      {
        key := (siOf[ufind(rn)] ?: "?") + "|" + (dispOf[ufind(rn)]?.symbol ?: "") + "|" + (kindOf[kfind(rn)]?.toStr ?: "?")
        byKey.getOrAdd(key) |->Str[]| { Str[,] }.add(rn)
      }
      i := 0
      byKey.each |group, key|
      {
        i++
        copy := i == 1 ? c : cloneConst(c, i)
        if (i > 1)
          group.each |rn|
          {
            dot := rn.indexr(".")
            reader := g.comps[rn[0..<dot]]
            slot := rn[dot+1..-1]
            reader.links[slot] = FlatLink(Ep(copy.name, "out"), reader.links[slot].cut)
          }
        // the reader first, so its group keeps its root and what is known of it
        join(group.first, node(copy.name, "out"), true)
        checkConstLabel(copy, group.first)
      }
    }
  }

  ** A copy of constant `c`. It keeps `cdlPath`, which names the CDL instance
  ** it runs, as the nodes of an expanded array share theirs; its `cdlPart`
  ** (`copy 2`) and its name tell it apart.
  private FlatComp cloneConst(FlatComp c, Int i)
  {
    nm := "${c.name}_$i"
    if (g.comps[nm] != null) throw CdlResolveErr("constant ${c.path} needs a copy named $nm, and a comp has that name")
    copy := g.add(nm, c.path, c.cdlPath, c.spec, c.cls, c.kind)
    c.vals.each |pv, slot| { copy.vals[slot] = pv.dup }
    c.extra.each |v, k| { copy.extra[k] = v }
    copy.extra["cdlPart"] = "copy $i"
    rules[nm] = rules[c.name]
    return copy
  }

  private Void checkConstLabel(FlatComp c, Str readerNode)
  {
    pv := c.vals["out"]
    if (pv == null || pv.role == "fixed") return
    label := norm(pv.si ?: litUnit(pv.raw))
    groupSi := siOf[ufind(readerNode)]
    if (label == null || groupSi == null || label == groupSi) return
    num := PVal.unwrap(pv.raw) as Number
    v := num?.toFloat ?: (pv.raw as Float)
    absTemp := kindOf[kfind(readerNode)] != true && Unit.fromStr(groupSi, false)?.dim == Unit("K").dim
    if (v == 0f && !absTemp)
    {
      // 0 is 0 in any unit and as any difference: it takes its group's unit
      pv.si = groupSi
      if (num != null) pv.raw = StatusNumber(Number(0f), Status.ok)
      return
    }
    throw CdlResolveErr("constant ${c.path} = ${Values.show(v)} is recorded in $label and feeds a unit group in $groupSi (" + members(readerNode) + ")")
  }

//////////////////////////////////////////////////////////////////////////
// Ratios
//////////////////////////////////////////////////////////////////////////

  **
  ** A Divide of two values in one unit gives a dimensionless ratio, but
  ** hx.comps (haystack `Number.divUnit`) labels it with an invented unit,
  ** `_m³/s/m³/s`, that no other value shares, so a comp that compares two
  ** such ratios faults. Each such Divide reads through an identity Line
  ** with unitless values on its second axis, which gives the ratio with no
  ** unit. The Line carries the Divide's path and `cdlPart` `ratio`.
  **
  private Void ratios()
  {
    g.comps.vals.each |fc|
    {
      r := rules[fc.name]
      if (r.op != "div") return
      a := ufind(node(fc.name, r.ins[0])); b := ufind(node(fc.name, r.ins[1]))
      u := siOf[a]
      if (a != b || u == null || u == "1") return
      from := Ep(fc.name, r.out)
      readers := g.comps.vals.findAll |x| { x.links.any |l| { l.from == from } }
      if (readers.isEmpty) return
      line := g.add("${fc.name}_ratio", fc.path, fc.cdlPath, lib.ns.spec("hx.comps::Line"), null, "ratio")
      line.extra["cdlPart"] = "ratio"
      line.vals["limitBelow"] = PVal.fixed(false)
      line.vals["limitAbove"] = PVal.fixed(false)
      line.vals["inX1"] = PVal.fixed(StatusNumber(Number(0f), Status.ok))
      line.vals["inX2"] = PVal.fixed(StatusNumber(Number(1f), Status.ok))
      line.vals["inF1"] = PVal.fixed(StatusNumber(Number(0f), Status.ok))
      line.vals["inF2"] = PVal.fixed(StatusNumber(Number(1f), Status.ok))
      line.links["in"] = FlatLink(from, false)
      to := Ep(line.name, "out")
      readers.each |x|
      {
        x.links.keys.each |slot|
        {
          l := x.links[slot]
          if (l.from == from) x.links[slot] = FlatLink(to, l.cut)
        }
      }
      rules[line.name] = UnitRule.none
      derived[node(line.name, "out")] = "1"
      readers.each |x| { x.links.each |l, slot| { if (l.from == to) join(node(line.name, "out"), node(x.name, slot), true) } }
    }
  }

//////////////////////////////////////////////////////////////////////////
// Rules
//////////////////////////////////////////////////////////////////////////

  ** A comp's unit rule in its own slot names
  private UnitRule ruleOf(FlatComp fc)
  {
    if (fc.synth != null) return fc.synth
    cls := fc.cls
    if (cls == null) return UnitRule.none
    if (fc.compound != null)
    {
      num := fc.compound.split('/').first
      line := lib.lineClass["connectors"] as Dict
      cg := cls["compoundGain"] as Dict ?: throw CdlResolveErr("${fc.path}: carries cdlCompoundGain and " + cls["cdlClass"] + " has no compoundGain")
      cm := fc.compoundMeta
      gain := cm?.get("gain")?.toStr ?: cg["gain"].toStr
      per := cm?.get("per")?.toStr ?: cg["per"].toStr
      if (cm != null && cm["perGroup"] != null && cm["perGroup"] != "u") throw CdlResolveErr("${fc.path}: cdlCompoundGain perGroup " + cm["perGroup"] + " is not u")
      zero := cg["zero"].toStr.split(',')
      return UnitRule([[line["u"].toStr, zero[0], per], [line["y"].toStr, gain, zero[1]]],
                      null, Str[,], null, [line["y"].toStr: num, gain: num])
    }
    rule := cls["unitRule"] as Dict
    if (rule == null) return UnitRule.none
    slot := |Str n->Str?| { slotOf(cls, n) }
    keep := Str[][,]
    (rule["keep"] as Str ?: "").split(';').each |grp|
    {
      names := grp.split(',').findAll { !it.isEmpty }
      slots := names.map |n->Str?| { slot(n) }.findAll { it != null }
      if (slots.size > 1) keep.add(slots)
    }
    ins := (rule["ins"] as Str ?: "").split(',').findAll { !it.isEmpty }.map |n->Str?| { slot(n) }.findAll { it != null }
    out := rule["out"] != null ? slot(rule["out"].toStr) : null
    seeds := Str:Str[:]
    (rule["seeds"] as Dict)?.each |u, n| { s := slot(n); if (s != null) seeds[s] = u.toStr }
    op := rule["op"] as Str
    if (op != null && (out == null || ins.isEmpty)) op = null
    return UnitRule(keep, op, ins, out, seeds)
  }

  ** The comp slot of a CDL name of a class: a connector, a parameter, or
  ** the slot a feed links into
  static Str? slotOf(Dict cls, Str n)
  {
    k := n.size > 0 && n[0].isUpper ? n[0..0].lower + n[1..-1] : n
    v := (cls["connectors"] as Dict)?.get(k) ?: (cls["params"] as Dict)?.get(k)
    if (v != null) return v.toStr
    f := (cls["feeds"] as Dict)?.get(k) as Dict
    return f?.get("slot")?.toStr
  }

//////////////////////////////////////////////////////////////////////////
// Union find
//////////////////////////////////////////////////////////////////////////

  private Str node(Str comp, Str slot)
  {
    n := "${comp}.${slot}"
    if (uparent[n] == null) { uparent[n] = n; kparent[n] = n }
    return n
  }

  private Str ufind(Str n) { find(uparent, n) }
  private Str kfind(Str n) { find(kparent, n) }

  private static Str find(Str:Str p, Str n)
  {
    root := n
    while (p[root] != root) root = p[root]
    while (p[n] != root) { next := p[n]; p[n] = root; n = next }
    return root
  }

  private Void join(Str a, Str b, Bool kind)
  {
    ra := ufind(a); rb := ufind(b)
    if (ra != rb) uparent[rb] = ra
    if (kind)
    {
      ka := kfind(a); kb := kfind(b)
      if (ka != kb) kparent[kb] = ka
    }
  }

  ** The members of the kind group of `n`, for a message
  private Str kmembers(Str n)
  {
    r := kfind(n)
    acc := kparent.keys.findAll { kfind(it) == r }.sort
    return acc.size > 12 ? acc[0..<12].join(", ") + ", and ${acc.size - 12} more" : acc.join(", ")
  }

  ** The members of the unit group of `n`, for a message
  private Str members(Str n)
  {
    r := ufind(n)
    acc := uparent.keys.findAll { ufind(it) == r }.sort
    return acc.size > 8 ? acc[0..<8].join(", ") + ", and ${acc.size - 8} more" : acc.join(", ")
  }

//////////////////////////////////////////////////////////////////////////
// SI units
//////////////////////////////////////////////////////////////////////////

  ** Every SI unit the slots of each unit group are known to carry
  private Str:Str collectSi()
  {
    acc := Str:Str[][:]
    from := Str:Str[:]
    add := |Str n, Str? u, Str? via|
    {
      if (u == null) return
      r := ufind(n)
      list := acc.getOrAdd(r) { Str[,] }
      if (!list.contains(u)) { list.add(u); from["$r|$u"] = via == null ? n : "$n, bound from parameter $via" }
    }
    derived.each |u, n| { add(n, u, null) }
    g.comps.each |fc|
    {
      fc.siSeeds.each |u, s| { add(node(fc.name, s), norm(u), null) }
      fc.siFacts.each |list, s| { list.each |u| { add(node(fc.name, s), norm(u), null) } }
      rules[fc.name].seeds.each |u, s| { add(node(fc.name, s), norm(u), null) }
      if (isConst(fc)) return
      fc.vals.each |pv, s|
      {
        if (pv.role == "fixed") return
        u := pv.si ?: litUnit(pv.raw)
        if (u != null) add(node(fc.name, s), norm(u), pv.si != null ? pv.siFrom : null)
      }
    }
    res := Str:Str[:]
    acc.each |list, r|
    {
      // a dimensionless fact is a fact: beside a unit it is a conflict
      if (list.size > 1) throw CdlResolveErr("unit group of " + members(r) + " mixes the units " + list.map |u| { "$u (from " + from["$r|$u"] + ")" }.join(" and "))
      res[r] = list.first
    }
    // a constant's own unit speaks for a reader group nothing else speaks for
    soft := Str:Str[][:]
    reads.each |readers, name|
    {
      pv := g.comps[name].vals["out"]
      u := norm(pv?.si ?: litUnit(pv?.raw))
      if (u == null) return
      readers.each |rn|
      {
        r := ufind(rn)
        if (res[r] != null) return
        list := soft.getOrAdd(r) { Str[,] }
        if (!list.contains(u)) list.add(u)
      }
    }
    soft.each |list, r| { if (list.size == 1) res[r] = list.first }
    return res
  }

  ** One spelling per unit: `s` and `sec` are one unit
  private static Str? norm(Str? u)
  {
    if (u == null) { return null }
    unit := Unit.fromStr(u, false)
    if (unit == null) return u
    return unit.symbol == "sec" ? "s" : unit.symbol
  }

  private static Str? litUnit(Obj? v)
  {
    v = PVal.unwrap(v)
    if (v is Number) return ((Number)v).unit?.symbol
    return null
  }

//////////////////////////////////////////////////////////////////////////
// Kinds
//////////////////////////////////////////////////////////////////////////

  ** Absolute or difference, for every kind group a fact reaches
  private Void kinds()
  {
    put := |Str n, Bool d|
    {
      r := kfind(n)
      old := kindOf[r]
      if (old != null && old != d) kindConflict[r] = true
      kindOf[r] = d
    }
    g.comps.each |fc|
    {
      fc.kindSeeds.each |d, s| { put(node(fc.name, s), d) }
      fc.kindFacts.each |list, s| { list.each |d| { put(node(fc.name, s), d) } }
      fc.vals.each |pv, s| { if (pv.delta != null && pv.role != "fixed") put(node(fc.name, s), pv.delta) }
    }
    changed := true
    while (changed)
    {
      changed = false
      g.comps.each |fc|
      {
        r := rules[fc.name]
        if (r.op == null) return
        o := kfind(node(fc.name, r.out))
        Bool? want := null
        // an input with no link and no value takes no part (a tree node's spare inputs)
        live := r.ins.findAll |s| { fc.links[s] != null || fc.vals[s] != null || r.op != "add" }
        ks := live.map |s->Bool?| { kindOf[kfind(node(fc.name, s))] }
        switch (r.op)
        {
          case "delta":
            want = true
          case "sub":
            if (ks.size == 2 && ks[0] == false && ks[1] == false) want = true
            else if (ks.size == 2 && ks[0] == false && ks[1] == true) want = false
            else if (ks.size == 2 && ks[0] == true && ks[1] == true) want = true
          case "add":
          case "sum":
            known := ks.findAll { it != null }
            if (!known.isEmpty && known.size == ks.size)
              want = known.any { it == false } ? false : true
          case "mul":
          case "div":
            ins := r.ins.map |s->Str| { node(fc.name, s) }
            dimless := ins.findAll { siOf[ufind(it)] == "1" }
            if (dimless.size == 1)
            {
              other := ins.find { siOf[ufind(it)] != "1" }
              want = kindOf[kfind(other)]
            }
        }
        if (want != null && kindOf[o] == null) { kindOf[o] = want; changed = true }
        if (backward(fc, r, live)) changed = true
      }
    }
  }

  **
  ** The kind of an add or sub input from its output and the other input.
  ** Counting an absolute temperature as 1 and a difference as 0, a sum's
  ** count is the sum of its inputs' and a difference's is their
  ** difference, and each count is 0 or 1.
  **
  private Bool backward(FlatComp fc, UnitRule r, Str[] live)
  {
    if ((r.op != "add" && r.op != "sub") || live.size != 2) return false
    a := kfind(node(fc.name, live[0])); b := kfind(node(fc.name, live[1])); o := kfind(node(fc.name, r.out))
    count := |Bool? d->Int?| { d == null ? null : (d ? 0 : 1) }
    ko := count(kindOf[o]); ka := count(kindOf[a]); kb := count(kindOf[b])
    if (ko == null) return false
    set := |Str k, Int c->Bool|
    {
      if (c < 0 || c > 1 || kindOf[k] != null) return false
      kindOf[k] = c == 0
      return true
    }
    if (r.op == "add")
    {
      if (ka != null && kb == null) return set(b, ko - ka)
      if (kb != null && ka == null) return set(a, ko - kb)
      if (ka == null && kb == null && ko == 0) return set(a, 0) || set(b, 0)
      return false
    }
    if (ka != null && kb == null) return set(b, ka - ko)
    if (kb != null && ka == null) return set(a, ko + kb)
    return false
  }

//////////////////////////////////////////////////////////////////////////
// Points
//////////////////////////////////////////////////////////////////////////

  **
  ** The point unit of every unit group a point comp reaches. A point unit
  ** must fit its connector: a dimensionless connector takes only its
  ** recorded point unit (ppm, or % left to the binder to scale); an absolute
  ** temperature takes an absolute unit and a difference a delta unit (Δ°F),
  ** whose group is then shown in the absolute one (°F).
  **
  private Void points()
  {
    g.comps.each |fc|
    {
      u := fc.pointUnit
      if (u == null || fc.pointSlot == null) return
      conn := fc.conn
      name := conn != null ? ParamEnv.cdlName(conn) : fc.name
      si := conn != null ? ParamEnv.siUnitOf(conn) : null
      if (si == null) throw CdlResolveErr("connector $name carries no unit, so point unit ${u.symbol} cannot apply")
      if (si == "1")
      {
        pu := conn?.meta?.get("cdlPointUnit")?.toStr
        if (pu != null && pu == u.symbol) return
        throw CdlResolveErr("connector $name is dimensionless" + (pu != null ? " and counted in $pu" : "") + "; point unit ${u.symbol} does not apply")
      }
      siUnit := Unit.fromStr(si, false) ?: throw CdlResolveErr("connector $name is in $si, which the unit database lacks; point unit ${u.symbol} cannot apply")
      if (siUnit.dim != u.dim) throw CdlResolveErr("connector $name is in $si; point unit ${u.symbol} does not convert to it")
      isDiff := Resolution.declaredDelta(conn) == true
      Unit shown := u
      if (u.symbol.startsWith("Δ"))
      {
        if (!isDiff) throw CdlResolveErr("connector $name is not declared a difference; point unit ${u.symbol} is one")
        shown = Unit.fromStr(u.symbol[1..-1], false) ?: throw CdlResolveErr("connector $name: point unit ${u.symbol} has no absolute unit")
      }
      else if (isDiff && siUnit.convertTo(0f, u) != 0f)
        throw CdlResolveErr("connector $name is a temperature difference; give its point unit as a difference (Δ${u.symbol}), not ${u.symbol}")
      if (siUnit == shown) return
      r := ufind(node(fc.name, fc.pointSlot))
      old := dispOf[r]
      if (old != null && old != shown)
        throw CdlResolveErr("unit group of " + members(r) + " reaches points in ${old.symbol} and ${shown.symbol}")
      dispOf[r] = shown
    }
  }

  **
  ** Every point comp states the unit it carries in the graph as
  ** `pointUnit`: its group's point unit, as a delta unit for a difference,
  ** so a binder knows what each point reads or writes, given or not.
  **
  private Void pointUnitsShown()
  {
    g.comps.each |fc|
    {
      if (fc.kind != "input" && fc.kind != "output") return
      slot := fc.kind == "input" ? "curVal" : "in"
      n := node(fc.name, slot)
      disp := dispOf[ufind(n)]
      if (disp == null) return
      diff := kindOf[kfind(n)] == true || Resolution.declaredDelta(fc.conn) == true
      sym := diff && Unit.fromStr(siOf[ufind(n)] ?: "", false)?.convertTo(0f, disp) != 0f ? "Δ" + disp.symbol : disp.symbol
      given := fc.pointUnit?.symbol
      if (given != null && given != sym && given != disp.symbol)
        throw CdlResolveErr("connector ${fc.cdlPath}: point unit $given, and its group carries $sym")
      fc.extra["pointUnit"] = sym
    }
  }

//////////////////////////////////////////////////////////////////////////
// Values
//////////////////////////////////////////////////////////////////////////

  private Void materialize()
  {
    g.comps.each |fc|
    {
      drop := Str[,]
      fc.vals.each |pv, slot|
      {
        if (pv.role == "fixed") return
        n := node(fc.name, slot)
        r := ufind(n)
        si := siOf[r]
        if (pv.onlyWithUnit && (si == null || si == "1")) { drop.add(slot); return }
        pv.written = value(fc, slot, pv, n, si, dispOf[r])
      }
      drop.each |s| { fc.vals.remove(s) }
    }
  }

  ** The value written to `slot`, coerced to the slot's type
  private Obj? value(FlatComp fc, Str slot, PVal pv, Str n, Str? groupSi, Unit? disp)
  {
    slotSpec := fc.spec.slot(slot, false)
    t := slotSpec?.type?.qname
    raw := pv.raw
    if (pv.role == "literal" || pv.role == "seed")
    {
      // a Fantom value from the library: convert only the number inside
      if (raw is StatusNumber)
      {
        sn := (StatusNumber)raw
        Str? su := sn.num.unit?.symbol
        if (su == null) su = pv.si
        if (su == null) su = groupSi
        return StatusNumber(numberIn(sn.num.toFloat, su, disp, pv, n), sn.status)
      }
      if (raw is Number && (t == "sys::Number" || t == null))
      {
        num := (Number)raw
        Str? nu := num.unit?.symbol
        if (nu == null) nu = pv.si
        if (nu == null) nu = groupSi
        return numberIn(num.toFloat, nu, disp, pv, n)
      }
      if (raw is Float && t == "sys::Float")
        return numberIn(raw, pv.si ?: groupSi, disp, pv, n).toFloat
      return raw
    }
    // a parameter value, as the evaluator holds it
    conv := pv.convert
    if (raw is Bool)
    {
      if (t == "hx.comps::StatusBool") return StatusBool(raw, Status.ok)
      return raw
    }
    if (raw is Str)
    {
      key := raw.toStr
      if (conv != null && conv.startsWith("enum "))
      {
        map := Str:Str[:]
        conv[5..-1].split.each |pair| { kv := pair.split('='); map[kv[0]] = kv[1] }
        key = map[key] ?: throw CdlResolveErr("${pv.what}: ${raw} has no entry in the conversion '$conv'")
      }
      if (slotSpec != null && slotSpec.type.isEnum) return slotSpec.type.binding.decodeScalar(key)
      return key
    }
    f := raw as Float ?: throw CdlResolveErr("${pv.what}: ${Values.show(raw)} cannot be written to ${fc.spec.qname}.$slot")
    if (conv == "sec" || t == "sys::Duration") return Duration((f * 1e9f).round.toInt)
    if (conv == "int" || t == "sys::Int")
    {
      if (f != f.floor) throw CdlResolveErr("${pv.what}: ${Values.show(f)} is written to an Int slot and is not whole")
      return f.toInt
    }
    num := pv.unitFixed ? Number(f, Unit.fromStr(pv.si ?: "", false)) : numberIn(f, pv.si ?: groupSi, disp, pv, n)
    if (conv == "float" || t == "sys::Float") return num.toFloat
    if (t == "hx.comps::StatusNumber") return StatusNumber(num, Status.ok)
    return num
  }

  ** A number in SI unit `si` written in the group's point unit `disp`, or
  ** in SI with no point unit. A converted value is rounded to 12 significant
  ** digits, so a conversion that is exact on paper is exact here (1 K is
  ** 1.8 Δ°F, not 1.8000000000000114).
  private Number numberIn(Float v, Str? si, Unit? disp, PVal pv, Str n)
  {
    siUnit := si == null || si == "1" ? null : Unit.fromStr(si, false)
    if (pv.unitFixed) return Number(v, siUnit)
    if (disp == null || siUnit == disp) return Number(v, siUnit)
    if (si == "1")
      throw CdlResolveErr("${pv.what}: ${Values.show(v)} is dimensionless and sits in a unit group converted to ${disp.symbol} (" + members(n) + ")")
    if (siUnit == null)
      throw CdlResolveErr("${pv.what}: its unit group (" + members(n) + ") is converted to ${disp.symbol}, and the value's own unit is not known")
    if (siUnit.dim != disp.dim)
      throw CdlResolveErr("${pv.what}: ${Values.show(v)} ${siUnit.symbol} sits in a unit group converted to ${disp.symbol}")
    offset := siUnit.convertTo(0f, disp)
    if (offset == 0f) return Number(tidy(siUnit.convertTo(v, disp)), disp)
    k := kfind(n)
    if (kindConflict[k] == true) throw CdlResolveErr("${pv.what}: its kind group mixes absolute temperatures and differences, so its value cannot convert to ${disp.symbol}")
    Bool? delta := pv.delta
    if (delta != null && kindOf[k] != null && kindOf[k] != delta)
      throw CdlResolveErr("${pv.what}: it is stated " + (delta ? "a difference" : "absolute") + ", and its kind group is " + (delta ? "absolute" : "a difference"))
    if (delta == null) delta = kindOf[k]
    if (delta == null)
      throw CdlResolveErr("${pv.what}: ${Values.show(v)} ${siUnit.symbol} converts to ${disp.symbol}, and nothing says whether it is an absolute temperature or a difference (its kind group: " + kmembers(n) + ")")
    // a difference takes the delta unit, as haystack gives °F less °F as Δ°F
    if (delta)
    {
      du := Unit.fromStr("Δ" + disp.symbol, false) ?: throw CdlResolveErr("${pv.what}: a difference in ${disp.symbol} has no delta unit in the unit database")
      return Number(tidy(siUnit.convertTo(v, disp) - offset), du)
    }
    return Number(tidy(siUnit.convertTo(v, disp)), disp)
  }

  ** `x` rounded to 12 significant digits
  static Float tidy(Float x)
  {
    // below 1e-290 the scale overflows: such a value is left as it is
    if (x == 0f || x.isNaN || x == Float.posInf || x == Float.negInf || x.abs < 1e-290f) return x
    scale := 10f.pow(11f - x.abs.log10.floor)
    return (x * scale).round / scale
  }
}
