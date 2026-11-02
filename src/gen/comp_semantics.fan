//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//
// A semantic anchor for the class-to-comp table that does not share the table's own reading of the comps: for one
// representative class of each family, set the CDL inputs and parameters on the hx.comps comp through the mapping
// in class-map.json, execute it, read the CDL outputs back through the mapping, and compare them with the value the
// CDL equation gives. The expected values are written here from the CDL equations, not from the table, so a swapped
// u1 and u2 on Subtract, or inTrue and inFalse on a switch, fails.
//
//   fan src/gen/comp_semantics.fan <class-map.json>
//
// Needs a Haxall whose hx.comps carries the comps the table names (haxall pull requests #138 to #152). Prints one
// line per case and "SEMANTICS PASS" or "SEMANTICS FAIL n"; exits 1 on any failure.
//
using concurrent
using util
using xeto
using haystack
using hxComps

class SemCx : CompContext
{
  new make(DateTime t) { now = t }
  override DateTime now
}

class CompSemantics
{
  ** class, CDL inputs, CDL parameters, expected CDL outputs (after the last step), and the input steps: each step
  ** sets its inputs, then executes once. A value is a Float (Real), an Int (Integer) or a Bool.
  static const Obj[][] cases := [
    ["RealsSubtract",  [["u1": 5f, "u2": 2f]], Str:Obj[:], ["y": 3f]],
    ["RealsDivide",    [["u1": 6f, "u2": 3f]], Str:Obj[:], ["y": 2f]],
    ["RealsAdd",       [["u1": 1f, "u2": 2f]], Str:Obj[:], ["y": 3f]],
    ["RealsMax",       [["u1": 1f, "u2": 4f]], Str:Obj[:], ["y": 4f]],
    ["RealsMin",       [["u1": 1f, "u2": 4f]], Str:Obj[:], ["y": 1f]],
    ["RealsAbs",       [["u": -3f]], Str:Obj[:], ["y": 3f]],
    ["RealsSwitch",    [["u1": 10f, "u2": true, "u3": 20f]], Str:Obj[:], ["y": 10f]],
    ["RealsSwitch",    [["u1": 10f, "u2": false, "u3": 20f]], Str:Obj[:], ["y": 20f]],
    ["LogicalSwitch",  [["u1": true, "u2": false, "u3": false]], Str:Obj[:], ["y": false]],
    ["LogicalAnd",     [["u1": true, "u2": false]], Str:Obj[:], ["y": false]],
    ["LogicalOr",      [["u1": true, "u2": false]], Str:Obj[:], ["y": true]],
    ["LogicalNot",     [["u": true]], Str:Obj[:], ["y": false]],
    ["IntegersEqual",  [["u1": 3, "u2": 3]], Str:Obj[:], ["y": true]],
    // Greater: y = not pre(y) and u1 > u2, or pre(y) and u1 > u2 - h. A nonzero h shows on the way back down: 2.5
    // keeps y true inside the band, 1.5 drops it. A dropped or misplaced h gives false on the first.
    ["RealsGreater",   [["u1": 5f, "u2": 3f]], ["h": 1f], ["y": true]],
    ["RealsGreater",   [["u1": 5f, "u2": 3f], ["u1": 2.5f, "u2": 3f]], ["h": 1f], ["y": true]],
    ["RealsGreater",   [["u1": 5f, "u2": 3f], ["u1": 1.5f, "u2": 3f]], ["h": 1f], ["y": false]],
    // Less: y = not pre(y) and u1 < u2, or pre(y) and u1 < u2 + h
    ["RealsLess",      [["u1": 5f, "u2": 3f]], ["h": 1f], ["y": false]],
    ["RealsLess",      [["u1": 1f, "u2": 3f], ["u1": 3.5f, "u2": 3f]], ["h": 1f], ["y": true]],
    // the threshold reaches inB through a NumberConst feed, and h stays a comp slot
    ["RealsGreaterThreshold", [["u": 5f], ["u": 2.5f]], ["t": 3f, "h": 1f], ["y": true]],
    ["RealsGreaterThreshold", [["u": 5f], ["u": 1.5f]], ["t": 3f, "h": 1f], ["y": false]],
    ["RealsLessThreshold",    [["u": 5f]], ["t": 3f, "h": 1f], ["y": false]],
    ["RealsLessThreshold",    [["u": 1f], ["u": 3.5f]], ["t": 3f, "h": 1f], ["y": true]],
    ["RealsAddParameter",        [["u": 1f]], ["p": 2f], ["y": 3f]],
    ["RealsMultiplyByParameter", [["u": 2f]], ["k": 3f], ["y": 6f]],
    ["ConversionsBooleanToReal", [["u": true]], ["realTrue": 7f, "realFalse": 2f], ["y": 7f]],
    ["ConversionsBooleanToReal", [["u": false]], ["realTrue": 7f, "realFalse": 2f], ["y": 2f]],
    ["ConversionsRealToInteger", [["u": 2.6f]], Str:Obj[:], ["y": 3f]],
    ["RealsLimiter",   [["u": 15f]], ["uMax": 10f, "uMin": 0f], ["y": 10f]],
    ["RealsLimiter",   [["u": -5f]], ["uMax": 10f, "uMin": 0f], ["y": 0f]],
    // y = f1 + (u - x1) * (f2 - f1) / (x2 - x1)
    ["RealsLine",      [["u": 0.25f, "x1": 0f, "f1": 2f, "x2": 1f, "f2": 10f]], ["limitBelow": false, "limitAbove": false], ["y": 4f]],
    // Hysteresis: true above uHigh, false below uLow
    ["RealsHysteresis", [["u": 4f]], ["uLow": 1f, "uHigh": 3f, "pre_y_start": false], ["y": true]],
    // Latch: a rise of u sets y, a rise of clr clears it
    ["LogicalLatch",   [["u": false, "clr": false], ["u": true, "clr": false]], Str:Obj[:], ["y": true]],
    ["LogicalLatch",   [["u": false, "clr": false], ["u": true, "clr": false], ["u": true, "clr": true]], Str:Obj[:], ["y": false]],
    // P control: y = k * (u_s - u_m) / r, within yMin..yMax, rising as u_m falls below u_s (reverse acting). r is 2,
    // so an r that never reaches the comp gives 0.2, not 0.1.
    ["RealsPid",       [["u_s": 1f, "u_m": 0.6f]], ["controllerType": "P", "k": 0.5f, "r": 2f, "yMax": 1f, "yMin": 0f, "reverseActing": true], ["y": 0.1f]],
    // TrueDelay: y turns true delayTime after u does. Each step is one second; a last execute adds one more.
    ["LogicalTrueDelay", [["u": false], ["u": true], ["u": true]], ["delayTime": 5f], ["y": false]],
    ["LogicalTrueDelay", [["u": false], ["u": true], ["u": true], ["u": true], ["u": true], ["u": true], ["u": true], ["u": true]], ["delayTime": 5f], ["y": true]],
    // TrueFalseHold: once true, y holds for trueHoldDuration even after u falls
    ["LogicalTrueFalseHold", [["u": false], ["u": true], ["u": false], ["u": false]], ["trueHoldDuration": 5f, "falseHoldDuration": 0f], ["y": true]],
    ["LogicalTrueFalseHold", [["u": false], ["u": true], ["u": false], ["u": false], ["u": false], ["u": false], ["u": false], ["u": false], ["u": false]], ["trueHoldDuration": 5f, "falseHoldDuration": 0f], ["y": false]],
  ]

  Int fails := 0

  Int main(Str[] args)
  {
    map := JsonInStream(File.os(args.first).in).readJson as Str:Obj?
    rows := map["classes"] as Str:Obj?
    ns := XetoEnv.cur.resolveNamespace(["hx.comps"])
    cs := CompSpace(ns).install.load(Folder()).start
    cx := SemCx(DateTime.fromIso("2026-10-31T12:00:00Z"))
    Actor.locals[ActorContext.actorLocalsKey] = cx
    cases.each |c|
    {
      name := (Str)c[0]
      try run(cs, cx, ns, name, rows[name], c[1], c[2], c[3])
      catch (Err e) { ++fails; echo("FAIL $name: $e") }
    }
    echo(fails == 0 ? "SEMANTICS PASS (${cases.size} cases)" : "SEMANTICS FAIL $fails of ${cases.size}")
    return fails == 0 ? 0 : 1
  }

  Void run(CompSpace cs, SemCx cx, Namespace ns, Str name, Str:Obj? row, Obj[] steps, Str:Obj params, Str:Obj want)
  {
    comp := cs.create(ns.spec((Str)row["comp"]))
    cs.root.add(comp)
    conns := row["connectors"] as Str:Obj?
    prms := row["params"] as Str:Obj?
    fixed := row["fixedSlots"] as Str:Obj?
    fixed.each |v, slot| { comp.set(slot, fixedVal(comp, slot, v)) }
    params.each |v, p|
    {
      pm := prms[p] as Str:Obj? ?: throw Err("$name has no parameter $p in the table")
      slot := (Str)pm["slot"]
      feed := (Str)pm["feed"]
      if (feed == "set") comp.set(slot, convert(v, pm["convert"] as Str))
      else
      {
        k := cs.create(ns.spec(feed))
        cs.root.add(k)
        k.set("out", status(v))
        link(k, comp, "out", slot)
      }
    }
    steps.each |Str:Obj step|
    {
      step.each |v, n|
      {
        m := conns[n] ?: throw Err("$name has no connector $n in the table")
        if (m isnot Str) throw Err("${name}.${n} reaches its slot through a feed; this anchor does not drive feeds")
        comp.set((Str)m, status(v))
      }
      cx.now = cx.now + 1sec
      cs.execute
    }
    // a second execute settles comps that push at the end of a cycle
    cx.now = cx.now + 1sec
    cs.execute
    Str[] bad := [,]
    want.each |v, n|
    {
      got := comp.get((Str)conns[n])
      if (!same(v, got)) bad.add("$n = $got, CDL gives $v")
    }
    if (bad.isEmpty) echo("pass $name ${steps.last}")
    else { ++fails; echo("FAIL $name ${steps.last}: " + bad.join("; ")) }
    cs.root.remove(comp.name)
  }

  static Void link(Comp from, Comp to, Str fromSlot, Str toSlot)
  {
    l := Etc.link(from.id, fromSlot)
    cur := to.get("links") as Links ?: Etc.links(null)
    to.set("links", cur.add(toSlot, l))
  }

  static Obj status(Obj v)
  {
    if (v is Bool) return StatusBool(v, Status.ok)
    if (v is Int) return StatusNumber(Number((Int)v), Status.ok)
    return StatusNumber(Number((Float)v), Status.ok)
  }

  ** A CDL parameter value converted per the table's conversion label
  static Obj convert(Obj v, Str? label)
  {
    if (label == null) return v is Float ? Number((Float)v) : v
    if (label.startsWith("Real seconds")) return Duration.fromStr("${v}sec")
    if (label == "Real to Float") return v is Int ? ((Int)v).toFloat : v
    if (label == "Integer to Int") return v is Float ? ((Float)v).toInt : v
    if (label.startsWith("TypesSimpleController")) return PidControllerType.fromStr(((Str)v).lower)
    if (label == "Integer to Number") return Number.makeNum((Num)v)
    return v is Float ? Number((Float)v) : v
  }

  static Obj fixedVal(Comp comp, Str slot, Obj? v)
  {
    if (v is Str && Regex<|^-?\d+(\.\d+)?(ms|sec|min|hr)$|>.matches(v)) return Duration.fromStr(v)
    if (v is Int && comp.spec.slot(slot).type.name == "Int") return v
    return v
  }

  ** Value and status: CDL has no status, so every output must read ok
  static Bool same(Obj want, Obj? got)
  {
    if (got is StatusBool) return ((StatusBool)got).status == Status.ok && want == ((StatusBool)got).val
    if (got is StatusNumber)
    {
      if (((StatusNumber)got).status != Status.ok) return false
      n := ((StatusNumber)got).num.toFloat
      w := want is Int ? ((Int)want).toFloat : (Float)want
      return (n - w).abs < 1e-9f
    }
    return false
  }
}
