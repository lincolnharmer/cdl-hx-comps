//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Expands one instance of a CDL array class onto hx.comps comps that
** exist, by its rule:
**   - reductions (MultiSum, MultiMax, MultiMin, MultiAnd, MultiOr) become a
**     balanced tree of 4-input comps;
**   - MatrixGain becomes one Add tree per row over its nonzero entries,
**     and MatrixMax and MatrixMin one Maximum or Minimum tree per row or
**     column;
**   - routing (the replicators, VectorFilter, ExtractSignal) is wiring and
**     makes no comp; Extractor is one select comp;
**   - Sort and the TimeTables refuse by name: no hx.comps comp runs them.
** Every comp it makes carries the instance's path and a `cdlPart`.
**
internal class ArrayExpand
{
  new make(Resolution r, Inst a)
  {
    this.r = r
    this.a = a
    this.cls = a.cls["cdlClass"].toStr
    this.name = cls["Buildings.Controls.OBC.CDL.".size..-1]
    this.base = a.flatName
  }

  Resolution r
  Inst a
  Str cls
  Str name
  Str base

  Str:Sig run()
  {
    switch (name)
    {
      case "Reals.MultiSum":     return ["y": reduceSum(true)]
      case "Integers.MultiSum":  return ["y": reduceSum(false)]
      case "Reals.MultiMax":     return ["y": reduce("hx.comps::Maximum", keepRule, null)]
      case "Reals.MultiMin":     return ["y": reduce("hx.comps::Minimum", keepRule, null)]
      case "Logical.MultiAnd":   return ["y": reduce("hx.comps::And", UnitRule.none, false)]
      case "Logical.MultiOr":    return ["y": reduce("hx.comps::Or", UnitRule.none, false)]
      case "Reals.MatrixGain":   return ["y": matrixGain]
      case "Reals.MatrixMax":    return ["y": matrixReduce("hx.comps::Maximum", "rowMax")]
      case "Reals.MatrixMin":    return ["y": matrixReduce("hx.comps::Minimum", "rowMin")]
      case "Routing.RealScalarReplicator":
      case "Routing.IntegerScalarReplicator":
      case "Routing.BooleanScalarReplicator": return ["y": scalarReplicator]
      case "Routing.RealVectorReplicator":
      case "Routing.IntegerVectorReplicator":
      case "Routing.BooleanVectorReplicator": return ["y": vectorReplicator]
      case "Routing.RealVectorFilter":
      case "Routing.IntegerVectorFilter":
      case "Routing.BooleanVectorFilter": return ["y": vectorFilter]
      case "Routing.RealExtractSignal":
      case "Routing.IntegerExtractSignal":
      case "Routing.BooleanExtractSignal": return ["y": extractSignal]
      case "Routing.RealExtractor":
      case "Routing.IntegerExtractor":     return ["y": extractor("hx.comps::NumberSelect")]
      case "Routing.BooleanExtractor":     return ["y": extractor("hx.comps::BoolSelect")]
    }
    throw CdlResolveErr("${a.path}: $cls has no expansion onto hx.comps comps (no comp runs it)")
  }

  static const Str[] quadIns := ["inA", "inB", "inC", "inD"]

  static UnitRule keepRule() { UnitRule([["inA", "inB", "inC", "inD", "out"]], null, Str[,], null, Str:Str[:]) }
  static UnitRule addRule() { UnitRule(Str[][,], "add", quadIns, "out", Str:Str[:]) }

  private Int num(Str n)
  {
    v := a.env[n] as Float ?: throw CdlResolveErr("${a.path}: $n is ${Values.show(a.env[n])}, not a number")
    if (v < 0f || v != v.floor) throw CdlResolveErr("${a.path}: $n is ${Values.show(v)}; a whole number >= 0 is required")
    return v.toInt
  }

  ** The signal into input `conn`, which must have shape `shape`
  private Sig input(Str conn, Int[] shape)
  {
    sig := r.arrayIn(a, conn) ?: throw CdlResolveErr("${a.path}.$conn: nothing drives it")
    if (!Sig.same(sig.shape, shape)) throw CdlResolveErr("${a.path}.$conn: has shape $shape and is driven with shape ${sig.shape}")
    return sig
  }

  private FlatComp comp(Str nm, Str qname, Str part, UnitRule rule)
  {
    fc := r.flatGraph.add(nm, a.path, a.cdlPath, r.ns.spec(qname), null, "tree")
    fc.extra["cdlPart"] = part
    fc.extra["cdlClass"] = cls
    fc.synth = rule
    return fc
  }

  private Ep constNum(Str nm, Float v, Str part)
  {
    old := r.flatGraph.get(nm)
    if (old != null)
    {
      // a shared constant: the comp of that name must be this constant
      same := old.extra["cdlClass"] == cls && old.spec.name == "NumberConst" && (old.vals["out"]?.written as StatusNumber)?.num == Number(v)
      if (!same) throw CdlResolveErr("${a.path}: constant $nm = ${Values.show(v)} clashes with comp ${old.path} of that name")
      return Ep(nm, "out")
    }
    fc := comp(nm, "hx.comps::NumberConst", part, UnitRule(Str[][,], null, Str[,], null, ["out": "1"]))
    fc.vals["out"] = PVal.fixed(StatusNumber(Number(v), Status.ok))
    return Ep(nm, "out")
  }

  private Ep constBool(Str nm, Bool v, Str part)
  {
    fc := comp(nm, "hx.comps::BoolConst", part, UnitRule.none)
    fc.vals["out"] = PVal.fixed(StatusBool(v, Status.ok))
    return Ep(nm, "out")
  }

  ** A balanced tree of 4-input comps over `leaves`, level by level
  private Ep tree(Ep[] leaves, Str qname, Str prefix, Str partPrefix, UnitRule rule)
  {
    cur := leaves
    level := 1
    while (cur.size > 1)
    {
      next := Ep[,]
      k := 0
      for (i := 0; i < cur.size; i += 4)
      {
        k++
        fc := comp("${prefix}L${level}_$k", qname, "${partPrefix}L${level}.$k", rule)
        cur[i..<(i+4).min(cur.size)].each |ep, j| { fc.links[quadIns[j]] = FlatLink(ep, false) }
        next.add(Ep(fc.name, "out"))
      }
      cur = next
      level++
    }
    return cur.first
  }

  private Sig scalar(Ep ep) { Sig([ep], Int[,]) }

  private Sig reduce(Str qname, UnitRule rule, Bool? emptyBool)
  {
    m := num("nin")
    if (m == 0)
    {
      if (emptyBool == null) throw CdlResolveErr("${a.path}: $cls over no inputs has no value in CDL")
      return scalar(constBool("${base}_empty", emptyBool, "empty"))
    }
    u := input("u", [m])
    return scalar(tree(u.eps, qname, "${base}_", "", rule))
  }

  ** y = sum of k[i]*u[i]: a gain of 1 links u[i] as it is, 0 drops it, -1
  ** negates it and any other multiplies it by a shared constant
  private Sig reduceSum(Bool real)
  {
    m := num("nin")
    if (m == 0) return scalar(constNum("${base}_zero", 0f, "empty"))
    u := input("u", [m])
    k := a.env["k"] as List ?: throw CdlResolveErr("${a.path}: k is not a list")
    if (k.size != m) throw CdlResolveErr("${a.path}: k has ${k.size} elements; nin is $m")
    leaves := Ep[,]
    u.eps.each |ep, i|
    {
      g := k[i] as Float
      if (g == 1f) leaves.add(ep)
      else if (g == 0f) return
      else if (g == -1f)
      {
        fc := comp("${base}_neg_${i+1}", "hx.comps::Negative", "neg.${i+1}", UnitRule([["inA", "out"]], null, Str[,], null, Str:Str[:]))
        fc.links["inA"] = FlatLink(ep, false)
        leaves.add(Ep(fc.name, "out"))
      }
      else
      {
        fc := comp("${base}_gain_${i+1}", "hx.comps::Multiply", "gain.${i+1}", UnitRule(Str[][,], "mul", ["inA", "inB"], "out", Str:Str[:]))
        fc.links["inA"] = FlatLink(ep, false)
        fc.links["inB"] = FlatLink(constNum("${base}_k${gainName(g)}", g, "k"), false)
        leaves.add(Ep(fc.name, "out"))
      }
    }
    if (leaves.isEmpty) return scalar(constNum("${base}_zero", 0f, "empty"))
    return scalar(tree(leaves, "hx.comps::Add", "${base}_", "", real ? addRule : UnitRule.none))
  }

  private static Str gainName(Float g) { FlatGraph.flatName(Values.show(g)).replace("-", "m").replace("+", "") }

  ** One Add tree per row of K over its nonzero entries
  private Sig matrixGain()
  {
    rows := a.env["K"] as List ?: throw CdlResolveErr("${a.path}: K is not a matrix")
    if (rows.isEmpty || !rows.all { it is List }) throw CdlResolveErr("${a.path}: K is not a list of rows")
    nin := ((List)rows.first).size
    u := input("u", [nin])
    eps := Ep[,]
    rows.each |List row, i|
    {
      terms := Ep[,]
      row.each |Float g, j|
      {
        ep := u.eps[j]
        if (g == 0f) return
        if (g == 1f) { terms.add(ep); return }
        if (g == -1f)
        {
          fc := comp("${base}_r${i+1}_neg_${j+1}", "hx.comps::Negative", "r${i+1}.neg.${j+1}", UnitRule([["inA", "out"]], null, Str[,], null, Str:Str[:]))
          fc.links["inA"] = FlatLink(ep, false)
          terms.add(Ep(fc.name, "out"))
          return
        }
        fc := comp("${base}_r${i+1}_gain_${j+1}", "hx.comps::Multiply", "r${i+1}.gain.${j+1}", UnitRule(Str[][,], "mul", ["inA", "inB"], "out", Str:Str[:]))
        fc.links["inA"] = FlatLink(ep, false)
        fc.links["inB"] = FlatLink(constNum("${base}_k${gainName(g)}", g, "k"), false)
        terms.add(Ep(fc.name, "out"))
      }
      if (terms.isEmpty) eps.add(constNum("${base}_zero", 0f, "zero"))
      else eps.add(tree(terms, "hx.comps::Add", "${base}_r${i+1}_", "r${i+1}.", addRule))
    }
    return Sig(eps, [rows.size])
  }

  ** One tree per row (or per column) of a run-time matrix
  private Sig matrixReduce(Str qname, Str rowParam)
  {
    nRow := num("nRow")
    nCol := num("nCol")
    byRow := a.env[rowParam] as Bool ?: throw CdlResolveErr("${a.path}: $rowParam is not a Boolean")
    u := input("u", [nRow, nCol])
    eps := Ep[,]
    if (byRow)
      for (i := 0; i < nRow; ++i)
        eps.add(tree(u.eps[i*nCol..<(i+1)*nCol], qname, "${base}_r${i+1}_", "r${i+1}.", keepRule))
    else
      for (j := 0; j < nCol; ++j)
        eps.add(tree((0..<nRow).toList.map |i->Ep| { u.eps[i*nCol+j] }, qname, "${base}_c${j+1}_", "c${j+1}.", keepRule))
    return Sig(eps, [eps.size])
  }

  private Sig scalarReplicator()
  {
    n := num("nout")
    u := input("u", Int[,])
    return u.copyFacts(Sig((1..n).toList.map |k->Ep| { u.eps.first }, [n]))
  }

  private Sig vectorReplicator()
  {
    nin := num("nin")
    nout := num("nout")
    u := input("u", [nin])
    eps := Ep[,]
    nout.times { eps.addAll(u.eps) }
    return u.copyFacts(Sig(eps, [nout, nin]))
  }

  private Sig vectorFilter()
  {
    nin := num("nin")
    nout := num("nout")
    msk := a.env["msk"] as List ?: throw CdlResolveErr("${a.path}: msk is not a list")
    if (msk.size != nin) throw CdlResolveErr("${a.path}: msk has ${msk.size} elements; nin is $nin")
    ids := Int[,]
    msk.each |v, i| { if (v == true) ids.add(i) }
    if (ids.size != nout) throw CdlResolveErr("${a.path}: msk selects ${ids.size} elements; nout is $nout")
    u := input("u", [nin])
    return u.copyFacts(Sig(ids.map |i->Ep| { u.eps[i] }, [nout]))
  }

  private Sig extractSignal()
  {
    nin := num("nin")
    nout := num("nout")
    ext := a.env["extract"] as List ?: throw CdlResolveErr("${a.path}: extract is not a list")
    if (ext.size != nout) throw CdlResolveErr("${a.path}: extract has ${ext.size} elements; nout is $nout")
    u := input("u", [nin])
    eps := ext.map |Float x->Ep|
    {
      i := x.toInt
      if (x != x.floor || i < 1 || i > nin) throw CdlResolveErr("${a.path}: extract names element ${Values.show(x)}, outside 1..$nin")
      return u.eps[i-1]
    }
    return u.copyFacts(Sig(eps, [nout]))
  }

  ** A select comp: one-based, clamped, as Extractor is
  private Sig extractor(Str qname)
  {
    nin := num("nin")
    u := input("u", [nin])
    if (nin == 1) return scalar(u.eps.first)
    if (nin > 10) throw CdlResolveErr("${a.path}: $cls over $nin inputs: no select comp takes more than 10")
    idx := input("index", Int[,])
    fc := comp("${base}_sel", qname, "sel", UnitRule([["inA", "inB", "inC", "inD", "inE", "inF", "inG", "inH", "inI", "inJ", "out"]], null, Str[,], null, Str:Str[:]))
    fc.vals["zeroBasedSelect"] = PVal.fixed(false)
    fc.vals["numInputs"] = PVal.fixed(nin.max(3))
    fc.links["select"] = FlatLink(idx.eps.first, false)
    slots := ["inA", "inB", "inC", "inD", "inE", "inF", "inG", "inH", "inI", "inJ"]
    u.eps.each |ep, i| { fc.links[slots[i]] = FlatLink(ep, false) }
    // a select takes at least 3 inputs: an index past 2 clamps to u[2], as CDL does
    if (nin == 2) fc.links["inC"] = FlatLink(u.eps[1], false)
    return scalar(Ep(fc.name, "out"))
  }
}
