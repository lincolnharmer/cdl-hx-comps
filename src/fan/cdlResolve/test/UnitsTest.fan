//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Units: SI by default, point units converting each group, absolute
** against difference, a PID's r and k, percent points, compound gains and
** ratios
**
class UnitsTest : ResolveTestBase
{
  static const Str src :=
    Str<|U1: kw.cdl::CdlBlock {
           dTHys: Number? <cdlParam, cdlName:"dTHys", cdlType:"Real", cdlUnit:"K", cdlDelta> "0.25"
           tSup: hx.comps::StatusNumber? <cdlInput, cdlName:"TSup", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tSet: hx.comps::StatusNumber? <cdlInput, cdlName:"TSet", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"lesThr.out">
           yGre: hx.comps::StatusBool? <cdlOutput, cdlName:"yGre", cdlType:"Boolean", transient, readonly, link:"gre.out">
           yPid: hx.comps::StatusNumber? <cdlOutput, cdlName:"yPid", cdlType:"Real", cdlUnit:"1", transient, readonly, link:"conPid.out">
           lesThr: hx.comps::LessThanHys? <cdlInstance, cdlName:"lesThr", cdlOf:@kw.cdl::cdl-RealsLessThreshold, cdlBind:{h:"dTHys"}> {
             inB: <link:"lesThr_t.out">
             inA: <link:"tSup">
           }
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> {
             inA: <link:"tSup">
             inB: <link:"tSet">
           }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold, cdlBind:{h:"dTHys"}> {
             inB: <link:"gre_t.out">
             inA: <link:"dif.out">
           }
           conPid: hx.comps::CdlPid? <cdlInstance, cdlName:"conPid", cdlOf:@kw.cdl::cdl-RealsPid, cdlBind:{k:"0.2"}> {
             inSetpoint: <link:"tSet">
             inMeasurement: <link:"tSup">
           }
           lesThr_t: hx.comps::NumberConst? <cdlFeed:"lesThr.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 277.55K } }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out"> { out: hx.comps::StatusNumber { val: 1K } }
         }
         U2: kw.cdl::CdlBlock {
           uDam: hx.comps::StatusNumber? <cdlInput, cdlName:"uDam", cdlType:"Real", cdlUnit:"1", unitless, cdlPointUnit:"%", cdlPointScale:"0.01">
           yDam: hx.comps::StatusNumber? <cdlOutput, cdlName:"yDam", cdlType:"Real", cdlUnit:"1", unitless, cdlPointUnit:"%", cdlPointScale:"0.01", transient, readonly, link:"lim.out">
           lim: hx.comps::Limiter? <cdlInstance, cdlName:"lim", cdlOf:@kw.cdl::cdl-RealsLimiter, cdlBind:{uMax:"0.95", uMin:"0.05"}> { in: <link:"uDam"> }
           pid: hx.comps::CdlPid? <cdlInstance, cdlName:"pid", cdlOf:@kw.cdl::cdl-RealsPid> {
             inSetpoint: <link:"uDam">
             inMeasurement: <link:"lim.out">
           }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inB: <link:"gre_t.out">, inA: <link:"uDam"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"1"}> { out: hx.comps::StatusNumber { val: 0.98 } }
         }
         U3: kw.cdl::CdlBlock {
           v1: hx.comps::StatusNumber? <cdlInput, cdlName:"V1", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow">
           v2: hx.comps::StatusNumber? <cdlInput, cdlName:"V2", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"1", transient, readonly, link:"div.out">
           div: hx.comps::Divide? <cdlInstance, cdlName:"div", cdlOf:@kw.cdl::cdl-RealsDivide> { inA: <link:"v1">, inB: <link:"v2"> }
         }
         U4: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"K", cdlDelta, transient, readonly, link:"div.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           cnt: hx.comps::NumberConst? <cdlInstance, cdlName:"cnt", cdlOf:@kw.cdl::cdl-IntegersSourcesConstant> { out: hx.comps::StatusNumber { val: 4 } }
           div: hx.comps::Divide? <cdlInstance, cdlName:"div", cdlOf:@kw.cdl::cdl-RealsDivide> { inA: <link:"dif.out">, inB: <link:"cnt.out", cdlLinkVia:"i2r"> }
           i2r: kw.cdl::CdlWire? <cdlInstance, cdlName:"i2r", cdlOf:@kw.cdl::cdl-ConversionsIntegerToReal>
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  static Dict fahr() { Etc.dict1("pointUnits", Etc.dict2("TSup", "°F", "TSet", "°F")) }

  ** Wrong behaviour caught: with no point units a literal or bound value
  ** converted anyway, or written without the SI unit of its signal; and a
  ** PID's r not written although its setpoint carries a unit.
  Void testSiByDefault()
  {
    g := resolve(lib, "U1")
    verifyNum(comp(g, "lesThr_t")["out"], 277.55f, "K")
    verifyNum(comp(g, "gre_t")["out"], 1f, "K")
    verifyNum(comp(g, "lesThr")["deadband"], 0.25f, "K")
    verifyEq(comp(g, "conPid")["r"], 1f)
    verifyEq(comp(g, "conPid")["k"], 0.2f)
  }

  ** Wrong behaviour caught: an absolute temperature converted by scale
  ** alone (277.55 K as 499.6 °F), a difference converted with the offset
  ** (1 K as -457.9 °F), or a difference written in °F, which hx.comps
  ** refuses beside a °F less °F.
  Void testAbsoluteAgainstDifference()
  {
    g := resolve(lib, "U1", Etc.dict0, fahr)
    verifyNum(comp(g, "lesThr_t")["out"], 39.92f, "°F")
    verifyNum(comp(g, "gre_t")["out"], 1.8f, "Δ°F")
    verifyNum(comp(g, "lesThr")["deadband"], 0.45f, "Δ°F")
    verifyNum(comp(g, "gre")["deadband"], 0.45f, "Δ°F")
  }

  ** Wrong behaviour caught: a PID's r left at 1 under °F (1.8 times the
  ** gain), or its k converted too (the loop converted twice), or yMax
  ** touched.
  Void testPidScale()
  {
    g := resolve(lib, "U1", Etc.dict0, fahr)
    verify((((Float)comp(g, "conPid")["r"]) - 1.8f).abs < 1e-9f)
    verifyEq(comp(g, "conPid")["k"], 0.2f)
    verifyEq(comp(g, "conPid")["yMax"], null)
  }

  ** Wrong behaviour caught: the graph behaving differently with °F points:
  ** a freeze threshold tripping at 277.55 °F, or the comparison faulting.
  Void testFahrenheitRuns()
  {
    cs := load(resolve(lib, "U1", Etc.dict0, fahr))
    sup := cs.root.get("TSup") ?: cs.root.get("tSup")
    set := cs.root.get("tSet") as Comp
    (set as Comp).set("curVal", StatusNumber(Number(70f, Unit("°F")), Status.ok))
    ((Comp)sup).set("curVal", StatusNumber(Number(40.5f, Unit("°F")), Status.ok))
    execute(cs)
    verifyEq(((StatusBool)(cs.root.get("y") as Comp).get("in")).bool, false)
    ((Comp)sup).set("curVal", StatusNumber(Number(39.5f, Unit("°F")), Status.ok))
    execute(cs)
    y := (StatusBool)(cs.root.get("y") as Comp).get("in")
    verifyEq(y.bool, true)
    verifyEq(y.status.isFault, false)
  }

  ** Wrong behaviour caught: a dimensionless group bound to a % point
  ** converted to percent, so 0.95 becomes 95, a PID's r or yMax written,
  ** or the point scale applied inside the graph rather than left for the
  ** binder at the boundary.
  Void testPercentPointKeepsFractions()
  {
    si := resolve(lib, "U2")
    pct := resolve(lib, "U2", Etc.dict0, Etc.dict1("pointUnits", Etc.dict2("uDam", "%", "yDam", "%")))
    ["lim", "pid", "gre", "gre_t"].each |n|
    {
      a := comp(si, n); b := comp(pct, n)
      a.each |v, k| { if (k != "links") verifyEq(b[k], v, n + "." + k) }
      verifyEq(Etc.dictNames(a).sort, Etc.dictNames(b).sort)
    }
    verifyNum(comp(pct, "lim")["uMax"], 0.95f, null)
    verifyEq(comp(pct, "pid")["r"], null)
    verifyEq(comp(pct, "pid")["yMax"], null)
    verifyEq(comp(pct, "uDam")["pointUnit"], "%")
    verifyEq(comp(pct, "uDam")["cdlPointScale"], Number(0.01f))
    verifyEq(linkOf(pct, "lim", "in"), "uDam.curVal")
  }

  ** Wrong behaviour caught: a point unit that does not fit the connector
  ** accepted (°F on a dimensionless one, Pa on a temperature).
  Void testPointUnitMustFit()
  {
    verifyRefuses(["uDam", "dimensionless", "°F"], |->Obj?| { return resolve(lib, "U2", Etc.dict0, Etc.dict1("pointUnits", Etc.dict1("uDam", "°F"))) })
    verifyRefuses(["TSup", "Pa"], |->Obj?| { return resolve(lib, "U1", Etc.dict0, Etc.dict1("pointUnits", Etc.dict1("TSup", "Pa"))) })
  }

  ** Wrong behaviour caught: a ratio of two flows left with hx.comps'
  ** invented unit `_m³/s/m³/s`, which faults the comp comparing it.
  Void testRatioReadsThroughUnitlessLine()
  {
    g := resolve(lib, "U3")
    verifyEq(linkOf(g, "y", "in"), "div_ratio.out")
    verifyEq(linkOf(g, "div_ratio", "in"), "div.out")
    cs := load(g)
    (cs.root.get("v1") as Comp).set("curVal", StatusNumber(Number(0.3f, Unit("m³/s")), Status.ok))
    (cs.root.get("v2") as Comp).set("curVal", StatusNumber(Number(0.6f, Unit("m³/s")), Status.ok))
    execute(cs)
    out := ((StatusNumber)(cs.root.get("y") as Comp).get("in")).num
    verifyEq(out.unit, null)
    verify((out.toFloat - 0.5f).abs < 1e-12f)
  }

  ** Wrong behaviour caught: TimeSuppression's s/K gain converted with the
  ** loop (540 s/K written as 300 s), or the Line's 1 K point left in K
  ** under °F so 1 °F reads as 1 K.
  Void testCompoundGain()
  {
    qn := "kw.cdl.g36.common::GenericTimeSuppression"
    si := CdlResolver(ns).resolve(qn, Etc.dict0)
    f := CdlResolver(ns).resolve(qn, Etc.dict0, Etc.dict1("pointUnits", Etc.dict2("TSet", "°F", "TZon", "°F")))
    verifyNum(valOf(si, "gai", "inF2"), 540f, "sec")
    verifyNum(valOf(f, "gai", "inF2"), 540f, "sec")
    verifyNum(valOf(si, "gai", "inX2"), 1f, "K")
    verifyNum(valOf(f, "gai", "inX2"), 1.8f, "Δ°F")
    verifyEq(comp(f, "gai")["spec"], Ref("hx.comps::Line"))
  }

  ** Wrong behaviour caught: a parameter left at the comp's unitless
  ** default (UnitDelay y_start 0) read in the point unit, so under °F it is
  ** 0 °F rather than 0 K and the first sample after start subtracts 0 °F
  ** from a °F setpoint, giving an absolute °F where a difference belongs.
  ** Written in SI too, so the default carries its signal's unit.
  Void testDefaultedStartTakesGroupUnit()
  {
    qn := "kw.cdl.g36.common::GenericTimeSuppression"
    si := CdlResolver(ns).resolve(qn, Etc.dict0)
    f := CdlResolver(ns).resolve(qn, Etc.dict0, Etc.dict1("pointUnits", Etc.dict2("TSet", "°F", "TZon", "°F")))
    verifyNum(comp(si, "uniDel")["yStart"], 0f, "K")
    verifyNum(comp(f, "uniDel")["yStart"], -459.67f, "°F")
    verifyNum(comp(f, "triSam1")["yStart"], -459.67f, "°F")
  }

  ** Wrong behaviour caught: a count read through Conversions.IntegerToReal
  ** taken as a value of unknown unit once the record is flattened away, so a
  ** temperature difference divided by it refuses under °F.
  Void testIntegerToRealIsDimensionless()
  {
    g := resolve(lib, "U4", Etc.dict0, Etc.dict1("pointUnits", Etc.dict2("TA", "°F", "TB", "°F")))
    verifyEq(linkOf(g, "div", "inB"), "cnt.out")
    verifyEq(linkOf(g, "y", "in"), "div.out")
  }

  ** Wrong behaviour caught: a point comp's cdlPath in Xeto slot names
  ** (tSup) where the CDL instance path spells it TSup.
  Void testCdlPathKeepsCdlSpelling()
  {
    g := resolve(lib, "U1")
    verifyEq(comp(g, "tSup")["cdlPath"], "TSup")
    verifyEq(comp(g, "lesThr")["cdlPath"], "lesThr")
  }
}
