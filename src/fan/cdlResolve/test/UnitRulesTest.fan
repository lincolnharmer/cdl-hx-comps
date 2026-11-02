//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** The unit pass rule by rule: how a constant is copied and labelled, what
** a mul or div infers, how add and sub grade temperatures, and what a
** refusal names
**
class UnitRulesTest : ResolveTestBase
{
  static const Str src :=
    Str<|R1: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusNumber? <cdlOutput, cdlName:"y2", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"max.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreater> { inA: <link:"dif.out">, inB: <link:"one.out"> }
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"tA">, inB: <link:"one.out"> }
           one: hx.comps::NumberConst? <cdlInstance, cdlName:"one", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 1K } }
         }
         R4: kw.cdl::CdlBlock {
           w: hx.comps::StatusNumber? <cdlInput, cdlName:"w", cdlType:"Real">
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"les.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y3: hx.comps::StatusBool? <cdlOutput, cdlName:"y3", cdlType:"Boolean", transient, readonly, link:"gre2.out">
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLess> { inA: <link:"w">, inB: <link:"kP.out"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreater> { inA: <link:"w">, inB: <link:"kK.out"> }
           gre2: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre2", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"w">, inB: <link:"gre2_t.out"> }
           gre2_t: hx.comps::NumberConst? <cdlFeed:"gre2.t"> { out: hx.comps::StatusNumber { val: 3 } }
           kP: hx.comps::NumberConst? <cdlInstance, cdlName:"kP", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"Pa"}> { out: hx.comps::StatusNumber { val: 10Pa } }
           kK: hx.comps::NumberConst? <cdlInstance, cdlName:"kK", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 5K } }
         }
         R6: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"max.out">
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"tA">, inB: <link:"zer.out"> }
           zer: hx.comps::NumberConst? <cdlInstance, cdlName:"zer", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"1"}> { out: hx.comps::StatusNumber { val: 0 } }
         }
         R7: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"gre.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreater> { inA: <link:"dif.out">, inB: <link:"five.out"> }
           five: hx.comps::NumberConst? <cdlInstance, cdlName:"five", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"Pa"}> { out: hx.comps::StatusNumber { val: 5Pa } }
         }
         R8: kw.cdl::CdlBlock {
           p: hx.comps::StatusNumber? <cdlInput, cdlName:"p", cdlType:"Real", cdlUnit:"Pa", quantity:"pressure">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"Pa", quantity:"pressure", transient, readonly, link:"max.out">
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"p">, inB: <link:"zer.out"> }
           zer: hx.comps::NumberConst? <cdlInstance, cdlName:"zer", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"m³/s"}> { out: hx.comps::StatusNumber { val: 0m³/s } }
         }
         D9: kw.cdl::CdlBlock {
           w: hx.comps::StatusNumber? <cdlInput, cdlName:"w", cdlType:"Real">
           uSig: hx.comps::StatusNumber? <cdlInput, cdlName:"uSig", cdlType:"Real", cdlUnit:"1", unitless>
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"gre2.out">
           div: hx.comps::Divide? <cdlInstance, cdlName:"div", cdlOf:@kw.cdl::cdl-RealsDivide> { inA: <link:"w">, inB: <link:"uSig"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"div.out">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"Pa"}> { out: hx.comps::StatusNumber { val: 20Pa } }
           gre2: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre2", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"w">, inB: <link:"gre2_t.out"> }
           gre2_t: hx.comps::NumberConst? <cdlFeed:"gre2.t"> { out: hx.comps::StatusNumber { val: 3 } }
         }
         D10: kw.cdl::CdlBlock {
           w: hx.comps::StatusNumber? <cdlInput, cdlName:"w", cdlType:"Real">
           v: hx.comps::StatusNumber? <cdlInput, cdlName:"V", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"1", unitless, transient, readonly, link:"div.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"gre2.out">
           div: hx.comps::Divide? <cdlInstance, cdlName:"div", cdlOf:@kw.cdl::cdl-RealsDivide> { inA: <link:"w">, inB: <link:"v"> }
           gre2: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre2", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"w">, inB: <link:"gre2_t.out"> }
           gre2_t: hx.comps::NumberConst? <cdlFeed:"gre2.t"> { out: hx.comps::StatusNumber { val: 3 } }
         }
         K12: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           dT: hx.comps::StatusNumber? <cdlInput, cdlName:"dT", cdlType:"Real", cdlUnit:"K", cdlDelta>
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"les.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"les2.out">
           sub: hx.comps::Subtract? <cdlInstance, cdlName:"sub", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"dT"> }
           add: hx.comps::Add? <cdlInstance, cdlName:"add", cdlOf:@kw.cdl::cdl-RealsAdd> { inA: <link:"tA">, inB: <link:"dT"> }
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLessThreshold> { inA: <link:"sub.out">, inB: <link:"les_t.out"> }
           les_t: hx.comps::NumberConst? <cdlFeed:"les.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 280K } }
           les2: hx.comps::LessThanHys? <cdlInstance, cdlName:"les2", cdlOf:@kw.cdl::cdl-RealsLessThreshold> { inA: <link:"add.out">, inB: <link:"les2_t.out"> }
           les2_t: hx.comps::NumberConst? <cdlFeed:"les2.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 280K } }
         }
         K14: kw.cdl::CdlBlock {
           w: hx.comps::StatusNumber? <cdlInput, cdlName:"w", cdlType:"Real">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"les.out">
           sub: hx.comps::Subtract? <cdlInstance, cdlName:"sub", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"w">, inB: <link:"tB"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"sub.out">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out"> { out: hx.comps::StatusNumber { val: 1K } }
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLessThreshold> { inA: <link:"w">, inB: <link:"les_t.out"> }
           les_t: hx.comps::NumberConst? <cdlFeed:"les.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 280K } }
         }
         P18: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "true"
           q: Number <cdlParam, cdlName:"q", cdlType:"Real", cdlEnable:"not mode">
           b: Number? <cdlParam, cdlName:"b", cdlType:"Real", cdlDefault:"2*q">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"b"}>
         }
         S4: kw.cdl::CdlBlock {
           hysD: Number? <cdlParam, cdlName:"hysD", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow"> "0.05"
           uDam: hx.comps::StatusNumber? <cdlInput, cdlName:"uDam", cdlType:"Real", cdlUnit:"1", unitless>
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"clo.out">
           clo: hx.comps::LessThanHys? <cdlInstance, cdlName:"clo", cdlOf:@kw.cdl::cdl-RealsLessThreshold, cdlBind:{h:"hysD"}> { inA: <link:"uDam">, inB: <link:"clo_t.out"> }
           clo_t: hx.comps::NumberConst? <cdlFeed:"clo.t", cdlLiteralUnits:{out:"1"}> { out: hx.comps::StatusNumber { val: 0.05 } }
         }
         N5: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"1", unitless, transient, readonly, link:"div.out">
           div: hx.comps::Divide? <cdlInstance, cdlName:"div", cdlOf:@kw.cdl::cdl-RealsDivide> { inA: <link:"tA">, inB: <link:"tB"> }
         }
         D22: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           dT: hx.comps::StatusNumber? <cdlInput, cdlName:"dT", cdlType:"Real", cdlUnit:"K", cdlDelta>
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"add.out">
           add: hx.comps::Add? <cdlInstance, cdlName:"add", cdlOf:@kw.cdl::cdl-RealsAdd> { inA: <link:"tA">, inB: <link:"dT"> }
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  static Dict pu(Str:Str m) { Etc.dict1("pointUnits", Etc.makeDict(m)) }

  ** Wrong behaviour caught (R1): a constant read by an absolute and by a
  ** difference reader of one unit kept as one comp, so one reader gets the
  ** other kind's value (1 K is -457.87 °F absolute and 1.8 Δ°F apart).
  Void testCopyKeyHoldsTheKind()
  {
    g := resolve(lib, "R1", Etc.dict0, pu(["TA": "°F", "TB": "°F"]))
    diff := linkOf(g, "gre", "inB").split('.').first
    abs := linkOf(g, "max", "inB").split('.').first
    verifyNotEq(diff, abs)
    verifyNum(comp(g, diff)["out"], 1.8f, "Δ°F")
    verifyNum(comp(g, abs)["out"], -457.87f, "°F")
  }

  ** Wrong behaviour caught (S1, R2, on the libraries): MZ's supply fan
  ** normalizer constant shared by the duct pressure measured in inH₂O and
  ** its setpoint held in Pa, so one of the two quotients is 248.84 times off.
  Void testCopyKeyHoldsThePointUnit()
  {
    ns2 := XetoEnv.cur.resolveNamespace(["kw.cdl.g36.ahu"])
    p := Etc.makeDict(["eneStd": "ASHRAE90_1", "venStd": "ASHRAE62_1", "VUncDesOutAir_flow": Number(0.8f), "VDesTotOutAir_flow": Number(1.0f), "VAbsOutAir_flow": Number(0.6f), "VDesOutAir_flow": Number(0.9f)])
    g := CdlResolver(ns2).resolve("kw.cdl.g36.ahu::AhusMultiZoneVavController", p, pu(["dpDuc": "inH₂O"]))
    mea := linkOf(g, "conSupFan_norPMea", "inB").split('.').first
    set := linkOf(g, "conSupFan_norPSet", "inB").split('.').first
    verifyNotEq(mea, set)
    verifyEq(num(comp(g, mea)["out"]).unit.symbol, "inH₂O")
    verifyNum(comp(g, set)["out"], 1000f, "Pa")
  }

  ** Wrong behaviour caught (R22): a difference point given in its group's
  ** delta unit refused, where it is the one unit it can take.
  Void testDeltaPointUnitAccepted()
  {
    g := resolve(lib, "D22", Etc.dict0, pu(["TA": "°F", "dT": "Δ°F"]))
    verifyEq(comp(g, "dT")["pointUnit"], "Δ°F")
  }

  ** Wrong behaviour caught (R4): two constants of different units speaking
  ** for one group of no other unit, the first one winning, so a third value
  ** in the group takes that unit.
  Void testConflictingSoftFactsSpeakForNothing()
  {
    g := resolve(lib, "R4")
    verifyNum(comp(g, "gre2_t")["out"], 3f, null)
  }

  ** Wrong behaviour caught (R6): a 0 recorded as dimensionless taking the
  ** unit of an absolute temperature group, where 0 K is not zero.
  Void testZeroIntoAbsoluteTemperatureRefuses()
  {
    verifyRefuses(["constant zer = 0 is recorded in 1", "K"], |->Obj?| { return resolve(lib, "R6") })
  }

  ** Wrong behaviour caught (R7): a non-zero constant of another unit taking
  ** its readers' unit, 5 Pa read as 5 K.
  Void testNonZeroOfAnotherUnitRefuses()
  {
    verifyRefuses(["constant five = 5 is recorded in Pa", "K"], |->Obj?| { return resolve(lib, "R7") })
  }

  ** Wrong behaviour caught (R8): a 0 recorded in another unit relabelled
  ** but still written in its old unit, 0 m³/s into a Pa comparison.
  Void testRelabelledZeroTakesItsGroupUnit()
  {
    g := resolve(lib, "R8")
    verifyNum(comp(g, "zer")["out"], 0f, "Pa")
  }

  ** Wrong behaviour caught (R9): a quotient by a dimensionless divisor not
  ** giving its dividend the quotient's unit.
  Void testDivBackwardThroughDimensionlessDivisor()
  {
    g := resolve(lib, "D9")
    verifyNum(comp(g, "gre2_t")["out"], 3f, "Pa")
  }

  ** Wrong behaviour caught (R10): a dimensionless quotient not putting its
  ** two inputs in one unit.
  Void testDimensionlessQuotientJoinsInputs()
  {
    g := resolve(lib, "D10")
    verifyNum(comp(g, "gre2_t")["out"], 3f, "m³/s")
  }

  ** Wrong behaviour caught (R12, R13): an absolute temperature less or plus
  ** a difference graded a difference, so an absolute threshold on it
  ** converts as 504 Δ°F rather than 44.33 °F.
  Void testAbsoluteWithDifferenceStaysAbsolute()
  {
    g := resolve(lib, "K12", Etc.dict0, pu(["TA": "°F", "dT": "Δ°F"]))
    verifyNum(comp(g, "les_t")["out"], 44.33f, "°F")
    verifyNum(comp(g, "les2_t")["out"], 44.33f, "°F")
  }

  ** Wrong behaviour caught (R14): the minuend of a difference whose result
  ** and subtrahend are known left of unknown kind, so an absolute threshold
  ** compared with it refuses.
  Void testSubBackwardGivesTheMinuendsKind()
  {
    g := resolve(lib, "K14", Etc.dict0, pu(["TB": "°F"]))
    verifyNum(comp(g, "les_t")["out"], 44.33f, "°F")
  }

  ** Wrong behaviour caught (R18): a default reading a disabled parameter
  ** reported as a missing value, with no word of the enable condition.
  Void testDefaultReadingDisabledParameterSaysWhy()
  {
    verifyRefuses(["the default of parameter b reads q", "enable condition (not mode) is false"], |->Obj?| { return resolve(lib, "P18") })
  }

  ** Wrong behaviour caught (S4): a unit-group conflict that names only the
  ** comp slot, not the parameter whose declaration brought the unit.
  Void testMixNamesTheBoundParameter()
  {
    verifyRefuses(["mixes the units", "bound from parameter hysD"], |->Obj?| { return resolve(lib, "S4") })
  }

  ** Wrong behaviour caught (N2): a difference parameter given in an
  ** absolute unit (°F) accepted, where a point would be refused.
  Void testDifferenceParameterNeedsDeltaUnit()
  {
    verifyRefuses(["parameter dT is a temperature difference", "Δ°F"], |->Obj?| { return resolve(temp(ParamsTest.src), "P4", Etc.dict1("dT", Number(1.8f, Unit("°F")))) })
  }

  ** Wrong behaviour caught (N5): a ratio of absolute temperatures accepted
  ** under °F, where it changes with the offset.
  Void testRatioOfAbsoluteTemperaturesRefuses()
  {
    resolve(lib, "N5")
    verifyRefuses(["div", "ratio of temperatures that are not both differences"], |->Obj?| { return resolve(lib, "N5", Etc.dict0, pu(["TA": "°F", "TB": "°F"])) })
  }

  ** Wrong behaviour caught (N3): a tiny value made NaN by the rounding.
  Void testTidyKeepsTinyValues()
  {
    verifyEq(UnitPass.tidy(1e-300f), 1e-300f)
    verifyEq(UnitPass.tidy(277.55f * 1.8f - 459.67f), 39.92f)
  }
}
