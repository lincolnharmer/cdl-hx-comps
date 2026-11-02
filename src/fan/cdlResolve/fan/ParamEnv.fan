//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack

**
** The parameters of one block: given values first, then each parameter's
** own default, then its `cdlDefault` expression, evaluated to a fixpoint
** so a default may read any parameter whose value is already known. The
** environment is keyed by CDL name and holds values in SI units.
**
internal class ParamEnv
{
  new make(CdlLib lib, Spec type, Str label)
  {
    this.lib = lib
    this.type = type
    this.label = label
    type.slots.each |s|
    {
      if (!s.meta.has("cdlParam")) return
      params.add(s)
    }
  }

  CdlLib lib
  Spec type
  Str label
  Spec[] params := [,]

  ** The CDL name of a parameter slot
  static Str cdlName(Spec s) { s.meta["cdlName"]?.toStr ?: s.name }

  ** The parameter slot of a CDL name, or null
  Spec? param(Str cdl) { params.find { cdlName(it) == cdl } }

  **
  ** Evaluate every parameter. `given` maps CDL names to evaluator values.
  ** A parameter with no value and no default refuses, unless its
  ** `cdlEnable` says it does not apply in this configuration; it is then
  ** left out, and any expression that reads it refuses naming it.
  **
  Str:Obj? eval(Str:Obj? given)
  {
    given.each |v, n|
    {
      p := param(n) ?: throw CdlResolveErr("$label: $n is not a parameter of ${type.qname}")
      if (p.meta.has("cdlProtected")) throw CdlResolveErr("$label: parameter $n is protected and takes no value")
    }
    env := Str:Obj?[:]
    env.setAll(given)
    // a parameter with no value, no own default and no default expression
    missing := params.findAll |p| { !env.containsKey(cdlName(p)) && p.metaOwn["val"] == null && p.meta["cdlDefault"] == null }
    missingNames := missing.map |p->Str| { cdlName(p) }
    pending := params.findAll |p| { !env.containsKey(cdlName(p)) && !missing.contains(p) }
    while (!pending.isEmpty)
    {
      left := Spec[,]
      pending.each |p|
      {
        n := cdlName(p)
        own := p.metaOwn["val"]
        expr := p.meta["cdlDefault"] as Str
        if (own != null) { env[n] = Values.toEnv(own); return }
        if (p.meta["cdlType"] == "String") { env[n] = expr; return }
        try
          env[n] = Expression.eval(expr, env, lib.dottedFunc)
        catch (CdlResolveErr e)
        {
          // defer only while every name it lacks is a parameter
          lacks := Expression.names(expr).findAll |x| { !x.contains(".") && !env.containsKey(x) }
          if (lacks.isEmpty || lacks.any |x| { param(x) == null }) throw CdlResolveErr("$label: the default of parameter $n: $e.msg")
          left.add(p)
        }
      }
      if (left.size >= pending.size) { stuck(left, env, missingNames); break }
      pending = left
    }
    missing.each |p|
    {
      n := cdlName(p)
      why := disabledBy(p, env)
      if (why != null) { exempt[n] = why; return }
      throw CdlResolveErr("$label: parameter $n has no default and no value")
    }
    checkShapes(env)
    return env
  }

  ** The parameters left out because their enable condition is false, to
  ** the condition, so a refusal that reads one can say why it has no value
  Str:Str exempt := [:]

  ** The enable condition that switches `p` off in `env`, or null
  private Str? disabledBy(Spec p, Str:Obj? env)
  {
    enable := p.meta["cdlEnable"] as Str
    if (enable == null) return null
    Obj? on
    try on = Expression.eval(enable, env, lib.dottedFunc)
    catch (CdlResolveErr e) throw CdlResolveErr("$label: parameter ${cdlName(p)} has no value, and its enable condition cannot be evaluated: $e.msg")
    return on == false ? enable : null
  }

  ** Defaults that cannot be evaluated: one that reads a parameter with no
  ** value names that parameter; a disabled one is left out; the rest form
  ** a cycle
  private Void stuck(Spec[] left, Str:Obj? env, Str[] missingNames)
  {
    cyclic := Spec[,]
    live := left.findAll |p|
    {
      why := disabledBy(p, env)
      if (why != null) exempt[cdlName(p)] = why
      return why == null
    }
    live.each |p|
    {
      n := cdlName(p)
      expr := p.meta["cdlDefault"].toStr
      lacks := Expression.names(expr).findAll |x| { !x.contains(".") && !env.containsKey(x) }
      off := lacks.find |x| { exempt[x] != null || (missingNames.contains(x) && disabledBy(param(x), env) != null) }
      if (off != null)
        throw CdlResolveErr("$label: the default of parameter $n reads $off, which has no value because its enable condition (" + (exempt[off] ?: disabledBy(param(off), env)) + ") is false")
      gap := lacks.find |x| { missingNames.contains(x) }
      if (gap != null) throw CdlResolveErr("$label: parameter $gap has no default and no value (the default of $n reads it)")
      cyclic.add(p)
    }
    if (cyclic.isEmpty) return
    throw CdlResolveErr("$label: the defaults of " + cyclic.map |p->Str| { cdlName(p) }.join(", ") + " read each other in a cycle (" +
      cyclic.map |p->Str| { cdlName(p) + " = " + p.meta["cdlDefault"] }.join("; ") + ")")
  }

  ** An array parameter's value must have the shape its size gives, and a
  ** scalar parameter's value must not be a list
  private Void checkShapes(Str:Obj? env)
  {
    params.each |p|
    {
      n := cdlName(p)
      if (!env.containsKey(n)) return
      v := env[n]
      sh := Values.shapeOf(v)
      size := p.meta["cdlArraySize"] as Str
      if (size == null)
      {
        if (!sh.isEmpty) throw CdlResolveErr("$label: parameter $n is not an array; its value is ${Values.show(v)}")
        return
      }
      size = stripParens(size.trim)
      if (size.isEmpty)
      {
        // an unsized array (MatrixGain K) takes its value's shape
        if (sh.isEmpty) throw CdlResolveErr("$label: parameter $n is an array; its value ${Values.show(v)} is a scalar")
        return
      }
      want := shape(size, env, "$label: parameter $n")
      if (!Sig.same(sh, want)) throw CdlResolveErr("$label: parameter $n has shape $sh; its size ($size) gives $want")
    }
  }

  ** The shape a size expression gives: `n` or `n1, n2`
  Int[] shape(Str size, Str:Obj? env, Str at)
  {
    splitTop(size).map |x->Int| { count(x, env, at) }
  }

  ** A size: `expr` evaluated in `env`, a whole number >= 0
  Int count(Str expr, Str:Obj? env, Str at)
  {
    n := Expression.eval(expr, env, lib.dottedFunc)
    f := n as Float
    if (f == null || f < 0f || f != f.floor) throw CdlResolveErr("$at: size $expr is ${Values.show(n)}; a whole number >= 0 is required")
    return f.toInt
  }

  ** One outer pair of parentheses off a size expression: `(nZon)` gives `nZon`
  static Str stripParens(Str text)
  {
    t := text.trim
    return t.startsWith("(") && t.endsWith(")") ? t[1..-2].trim : t
  }

  ** Split at top-level commas
  static Str[] splitTop(Str s)
  {
    acc := Str[,]
    depth := 0
    start := 0
    s.each |ch, i|
    {
      if (ch == '(' || ch == '{' || ch == '[') depth++
      else if (ch == ')' || ch == '}' || ch == ']') depth--
      else if (ch == ',' && depth == 0) { acc.add(s[start..<i].trim); start = i + 1 }
    }
    acc.add(s[start..-1].trim)
    return acc
  }

//////////////////////////////////////////////////////////////////////////
// Bounds
//////////////////////////////////////////////////////////////////////////

  **
  ** Check every parameter value against the bounds its declaration gives:
  ** `minVal` and `maxVal`, `cdlSiMin` and `cdlSiMax` (in SI, as the
  ** environment is), each `cdlMinWhen` or `cdlMaxWhen` case whose condition
  ** holds, and `cdlMinExpr` or `cdlMaxExpr`.
  **
  Void checkBounds(Str:Obj? env)
  {
    params.each |p|
    {
      n := cdlName(p)
      v := env[n]
      if (v == null) return
      m := p.meta
      via := m["cdlMinVia"] != null ? " (from " + m["cdlMinVia"] + ")" : ""
      viaMax := m["cdlMaxVia"] != null ? " (from " + m["cdlMaxVia"] + ")" : ""
      checkOne(n, v, num(m["minVal"]), true, via)
      checkOne(n, v, num(m["maxVal"]), false, viaMax)
      checkOne(n, v, num(m["cdlSiMin"]), true, via)
      checkOne(n, v, num(m["cdlSiMax"]), false, viaMax)
      whenCases(n, v, m["cdlMinWhen"], true, env)
      whenCases(n, v, m["cdlMaxWhen"], false, env)
      exprBound(n, v, m["cdlMinExpr"], true, env)
      exprBound(n, v, m["cdlMaxExpr"], false, env)
    }
  }

  private static Float? num(Obj? x)
  {
    if (x is Number) return ((Number)x).toFloat
    if (x is Float) return x
    if (x is Int) return ((Int)x).toFloat
    if (x is Str) return Float.fromStr(x, false)
    return null
  }

  private Void checkOne(Str n, Obj? v, Float? bound, Bool isMin, Str via)
  {
    if (bound == null) return
    Values.flat(v).each |x|
    {
      f := x as Float
      if (f == null) return
      if (isMin && f < bound)
        throw CdlResolveErr("$label: parameter $n = ${Values.show(f)} is below its minimum ${Values.show(bound)}$via")
      if (!isMin && f > bound)
        throw CdlResolveErr("$label: parameter $n = ${Values.show(f)} is above its maximum ${Values.show(bound)}$via")
    }
  }

  private Void whenCases(Str n, Obj? v, Obj? cases, Bool isMin, Str:Obj? env)
  {
    list := cases as List
    if (list == null) return
    list.each |Dict c|
    {
      cond := c["cond"].toStr
      Obj? holds
      try holds = Expression.eval(cond, env, lib.dottedFunc)
      catch (CdlResolveErr e) throw CdlResolveErr("$label: the bound case of parameter $n cannot be evaluated: $e.msg")
      if (holds != true) return
      checkOne(n, v, num(c["val"]), isMin, " (when $cond, from " + c["via"] + ")")
    }
  }

  private Void exprBound(Str n, Obj? v, Obj? expr, Bool isMin, Str:Obj? env)
  {
    if (expr == null) return
    b := Expression.eval(expr.toStr, env, lib.dottedFunc)
    checkOne(n, v, b as Float, isMin, " (= $expr)")
  }

//////////////////////////////////////////////////////////////////////////
// Given values
//////////////////////////////////////////////////////////////////////////

  **
  ** The caller's parameter values as evaluator values in SI. A Number with
  ** a unit converts into the parameter's SI unit: an absolute value with
  ** the offset, a `cdlDelta` value by scale alone. A unitless Number is
  ** taken as SI. A value whose type does not fit the parameter refuses.
  **
  Str:Obj? fromGiven(Dict given)
  {
    acc := Str:Obj?[:]
    given.each |v, n|
    {
      p := param(n) ?: throw CdlResolveErr("$label: $n is not a parameter of ${type.qname}" + hint(n))
      if (p.meta.has("cdlProtected")) throw CdlResolveErr("$label: parameter $n is protected and takes no value")
      if (p.meta.has("cdlFinal")) throw CdlResolveErr("$label: parameter $n is final and takes no value")
      acc[n] = givenVal(p, n, v)
    }
    return acc
  }

  private Str hint(Str n)
  {
    s := type.slot(n, false)
    if (s != null && s.meta.has("cdlParam")) return "; its CDL name is ${cdlName(s)}"
    return ""
  }

  private Obj? givenVal(Spec p, Str n, Obj? v)
  {
    if (v is List) return ((List)v).map |x->Obj?| { givenVal(p, n, x) }
    t := p.meta["cdlType"]?.toStr ?: "Real"
    switch (t)
    {
      case "Boolean":
        if (v isnot Bool) throw CdlResolveErr("$label: parameter $n is a Boolean; given ${v} (${v?.typeof})")
        return v
      case "Integer":
        f := plainNum(n, v, t)
        if (f != f.floor) throw CdlResolveErr("$label: parameter $n is an Integer; given ${Values.show(f)}")
        return f
      case "Real":
        return realNum(p, n, v)
      case "String":
        if (v isnot Str) throw CdlResolveErr("$label: parameter $n is a String; given ${v}")
        return v
    }
    // an enumeration, named by its spec qname
    e := lib.ns.spec(t, false)
    if (e == null || !e.isEnum) throw CdlResolveErr("$label: parameter $n has type $t, which the resolver cannot read")
    key := v?.toStr
    keys := lib.enumKeys(e)
    if (!keys.contains(key)) throw CdlResolveErr("$label: parameter $n takes one of " + keys.join(", ") + "; given $key")
    return key
  }

  private Float plainNum(Str n, Obj? v, Str t)
  {
    if (v is Number)
    {
      num := (Number)v
      if (num.unit != null) throw CdlResolveErr("$label: parameter $n is an $t and takes no unit; given $num")
      return num.toFloat
    }
    if (v is Int) { count := (Int)v; return count.toFloat }
    if (v is Float) return v
    throw CdlResolveErr("$label: parameter $n is an $t; given ${v}")
  }

  private Float realNum(Spec p, Str n, Obj? v)
  {
    if (v is Float) return v
    if (v is Int) { whole := (Int)v; return whole.toFloat }
    num := v as Number ?: throw CdlResolveErr("$label: parameter $n is a Real; given ${v}")
    if (num.unit == null) return num.toFloat
    si := siUnitOf(p)
    if (si == null || si == "1")
      throw CdlResolveErr("$label: parameter $n carries no unit; given $num")
    siUnit := Unit.fromStr(si, false) ?: throw CdlResolveErr("$label: parameter $n is in $si, which the unit database lacks; give it unitless, in $si")
    if (num.unit == siUnit) return num.toFloat
    if (num.unit.dim != siUnit.dim) throw CdlResolveErr("$label: parameter $n is in $si; given $num, which does not convert")
    // a difference is given in a delta unit, as a point carrying one must be
    offsetUnit := num.unit.convertTo(0f, siUnit) != 0f
    if (isDelta(p) && offsetUnit && !num.unit.symbol.startsWith("Δ"))
      throw CdlResolveErr("$label: parameter $n is a temperature difference; give it in a delta unit (Δ${num.unit.symbol}), not $num")
    if (isDelta(p)) return num.unit.convertTo(num.toFloat, siUnit) - num.unit.convertTo(0f, siUnit)
    if (num.unit.symbol.startsWith("Δ")) throw CdlResolveErr("$label: parameter $n is an absolute value; given $num, a difference")
    return num.unit.convertTo(num.toFloat, siUnit)
  }

  ** The SI unit a slot declares: `cdlUnit`, or `cdlUnitInferred`
  static Str? siUnitOf(Spec s) { s.meta["cdlUnit"]?.toStr ?: s.meta["cdlUnitInferred"]?.toStr }

  ** True for a temperature difference
  static Bool isDelta(Spec s) { s.meta.has("cdlDelta") || s.meta["cdlQuantityKind"] == "TemperatureDifference" }
}
