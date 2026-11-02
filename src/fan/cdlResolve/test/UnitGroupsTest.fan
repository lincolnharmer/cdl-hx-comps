//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Unit groups: constants that feed several domains, dimensionless facts,
** bound parameter units, inference through products, the point-unit
** contract and the causes refusals name
**
class UnitGroupsTest : ResolveTestBase
{
  static const Str src :=
    Str<|G1: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           uSig: hx.comps::StatusNumber? <cdlInput, cdlName:"uSig", cdlType:"Real", cdlUnit:"1", unitless>
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusNumber? <cdlOutput, cdlName:"y2", cdlType:"Real", cdlUnit:"1", unitless, transient, readonly, link:"max.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreater> { inA: <link:"dif.out">, inB: <link:"zer.out"> }
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"uSig">, inB: <link:"zer.out"> }
           zer: hx.comps::NumberConst? <cdlInstance, cdlName:"zer", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlLiteralUnits:{out:"1"}> { out: hx.comps::StatusNumber { val: 0 } }
         }
         G2: kw.cdl::CdlBlock {
           hys: Number? <cdlParam, cdlName:"hys", cdlType:"Real", cdlUnit:"1", unitless> "0.05"
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"les.out">
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLessThreshold, cdlBind:{t:"hys"}> { inA: <link:"tA">, inB: <link:"les_t.out"> }
           les_t: hx.comps::NumberConst? <cdlFeed:"les.t">
         }
         G3: kw.cdl::CdlBlock {
           floHys: Number? <cdlParam, cdlName:"floHys", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow"> "0.01"
           v: hx.comps::StatusNumber? <cdlInput, cdlName:"V", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"gre.out">
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold, cdlBind:{h:"floHys"}> { inA: <link:"v">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"m³/s"}> { out: hx.comps::StatusNumber { val: 0.2m³/s } }
         }
         G4: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"gre.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           gai: hx.comps::Multiply? <cdlInstance, cdlName:"gai", cdlOf:@kw.cdl::cdl-RealsMultiply> { inA: <link:"dif.out">, inB: <link:"k.out"> }
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant> { out: hx.comps::StatusNumber { val: 0.5 } }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"gai.out">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out"> { out: hx.comps::StatusNumber { val: 1K } }
         }
         G5: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "true"
           q: Number <cdlParam, cdlName:"q", cdlType:"Real", cdlEnable:"not mode">
           b: Number? <cdlParam, cdlName:"b", cdlType:"Real", cdlDefault:"2*r">
           r: Number <cdlParam, cdlName:"r", cdlType:"Real">
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           dT: hx.comps::StatusNumber? <cdlInput, cdlName:"dT", cdlType:"Real", cdlUnit:"K", cdlDelta>
           tOld: hx.comps::StatusNumber? <cdlInput, cdlName:"TOld", cdlType:"Real", cdlUnit:"K", quantity:"temperature", cdlCondition:"not mode">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"add.out">
           add: hx.comps::Add? <cdlInstance, cdlName:"add", cdlOf:@kw.cdl::cdl-RealsAdd> { inA: <link:"tA">, inB: <link:"dT"> }
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"b"}>
         }
         G6: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "true"
           q: Number <cdlParam, cdlName:"q", cdlType:"Real", cdlEnable:"not mode">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"q"}>
         }
         G7: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"les.out">
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLessThreshold> { inA: <link:"tA">, inB: <link:"les_t.out"> }
           les_t: hx.comps::NumberConst? <cdlFeed:"les.t", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out"> { out: hx.comps::StatusNumber { val: 280K } }
         }
         G8: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"max.out">
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"tA">, inB: <link:"tB"> }
         }
         G9: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           tB: hx.comps::StatusNumber? <cdlInput, cdlName:"TB", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"gre.out">
           dif: hx.comps::Subtract? <cdlInstance, cdlName:"dif", cdlOf:@kw.cdl::cdl-RealsSubtract> { inA: <link:"tA">, inB: <link:"tB"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"dif.out">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 2K } }
         }
         G10: kw.cdl::CdlBlock {
           u1: hx.comps::StatusNumber? <cdlInput, cdlName:"u1", cdlType:"Real", cdlUnit:"1", unitless>
           u2: hx.comps::StatusNumber? <cdlInput, cdlName:"u2", cdlType:"Real", cdlUnit:"1", unitless>
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"les.out">
           pro: hx.comps::Multiply? <cdlInstance, cdlName:"pro", cdlOf:@kw.cdl::cdl-RealsMultiply> { inA: <link:"u1">, inB: <link:"u2"> }
           les: hx.comps::LessThanHys? <cdlInstance, cdlName:"les", cdlOf:@kw.cdl::cdl-RealsLessThreshold> { inA: <link:"pro.out">, inB: <link:"les_t.out"> }
           les_t: hx.comps::NumberConst? <cdlFeed:"les.t", cdlLiteralUnits:{out:"K"}> { out: hx.comps::StatusNumber { val: 280K } }
         }
         G11In: kw.cdl::CdlBlock {
           p: hx.comps::StatusNumber? <cdlInput, cdlName:"p", cdlType:"Real", cdlUnit:"Pa", quantity:"pressure">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"gre.out">
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"p">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t"> { out: hx.comps::StatusNumber { val: 5 } }
         }
         G11: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"inn.y">
           inn: G11In? <cdlInstance, cdlName:"inn"> { p: <link:"u"> }
         }
         G12: kw.cdl::CdlBlock {
           tA: hx.comps::StatusNumber? <cdlInput, cdlName:"TA", cdlType:"Real", cdlUnit:"K", quantity:"temperature">
           v: hx.comps::StatusNumber? <cdlInput, cdlName:"V", cdlType:"Real", cdlUnit:"m³/s", quantity:"volumetricFlow">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"pro.out">
           pro: hx.comps::Multiply? <cdlInstance, cdlName:"pro", cdlOf:@kw.cdl::cdl-RealsMultiply> { inA: <link:"tA">, inB: <link:"v"> }
         }
         G13: kw.cdl::CdlBlock {
           u1: hx.comps::StatusNumber? <cdlInput, cdlName:"u1", cdlType:"Real", cdlUnit:"1", unitless>
           u2: hx.comps::StatusNumber? <cdlInput, cdlName:"u2", cdlType:"Real", cdlUnit:"1", unitless>
           uSig: hx.comps::StatusNumber? <cdlInput, cdlName:"uSig", cdlType:"Real", cdlUnit:"1", unitless>
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusNumber? <cdlOutput, cdlName:"y2", cdlType:"Real", transient, readonly, link:"max.out">
           pro: hx.comps::Multiply? <cdlInstance, cdlName:"pro", cdlOf:@kw.cdl::cdl-RealsMultiply> { inA: <link:"u1">, inB: <link:"u2"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreater> { inA: <link:"pro.out">, inB: <link:"k.out"> }
           max: hx.comps::Maximum? <cdlInstance, cdlName:"max", cdlOf:@kw.cdl::cdl-RealsMax> { inA: <link:"uSig">, inB: <link:"k.out"> }
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant> { out: hx.comps::StatusNumber { val: 0.5 } }
         }
         G14: kw.cdl::CdlBlock {
           uSig: hx.comps::StatusNumber? <cdlInput, cdlName:"uSig", cdlType:"Real", cdlUnit:"1", unitless>
           w: hx.comps::StatusNumber? <cdlInput, cdlName:"w", cdlType:"Real">
           y1: hx.comps::StatusBool? <cdlOutput, cdlName:"y1", cdlType:"Boolean", transient, readonly, link:"gre.out">
           y2: hx.comps::StatusBool? <cdlOutput, cdlName:"y2", cdlType:"Boolean", transient, readonly, link:"gre2.out">
           pro: hx.comps::Multiply? <cdlInstance, cdlName:"pro", cdlOf:@kw.cdl::cdl-RealsMultiply> { inA: <link:"uSig">, inB: <link:"w"> }
           gre: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"pro.out">, inB: <link:"gre_t.out"> }
           gre_t: hx.comps::NumberConst? <cdlFeed:"gre.t", cdlLiteralUnits:{out:"K"}, cdlLiteralDelta:"out"> { out: hx.comps::StatusNumber { val: 2K } }
           gre2: hx.comps::GreaterThanHys? <cdlInstance, cdlName:"gre2", cdlOf:@kw.cdl::cdl-RealsGreaterThreshold> { inA: <link:"w">, inB: <link:"gre2_t.out"> }
           gre2_t: hx.comps::NumberConst? <cdlFeed:"gre2.t"> { out: hx.comps::StatusNumber { val: 3 } }
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  static Dict pu(Str:Str m) { Etc.dict1("pointUnits", Etc.makeDict(m)) }

  ** Wrong behaviour caught: one constant joining a temperature difference
  ** and a 0 to 1 signal into one group, so the signal is converted with
  ** the temperatures (B1).
  Void testConstantSplitPerDomain()
  {
    g := resolve(lib, "G1", Etc.dict0, pu(["TA": "°F", "TB": "°F"]))
    verifyEq(compNames(g).findAll { it.startsWith("zer") }, ["zer", "zer_2"])
    temp := linkOf(g, "gre", "inB").split('.').first
    sig := linkOf(g, "max", "inB").split('.').first
    verifyNotEq(temp, sig)
    verifyNum(comp(g, temp)["out"], 0f, "Δ°F")
    verifyNum(comp(g, sig)["out"], 0f, null)
  }

  ** Wrong behaviour caught: a dimensionless fact dropped beside a unit, so a
  ** "1" parameter is written into a temperature comparison (B1).
  Void testDimensionlessBesideUnitRefuses()
  {
    verifyRefuses(["mixes the units", "1", "K"], |->Obj?| { return resolve(lib, "G2") })
  }

  ** Wrong behaviour caught: a bound parameter written unitless although its
  ** declaration gives its SI unit.
  Void testBoundParameterCarriesItsUnit()
  {
    g := resolve(lib, "G3")
    verifyNum(comp(g, "gre")["deadband"], 0.01f, "m³/s")
    c := resolve(lib, "G3", Etc.dict0, pu(["V": "cfm"]))
    verifyNum(comp(c, "gre")["deadband"], 21.1888000328931f, "cfm")
    verifyNum(comp(c, "gre_t")["out"], 423.776000657863f, "cfm")
  }

  ** Wrong behaviour caught: a gain of no recorded unit left unknown, so a
  ** product of a temperature difference refuses under °F although its
  ** output's group says the gain is dimensionless (S1).
  Void testProductInfersBackward()
  {
    g := resolve(lib, "G4", Etc.dict0, pu(["TA": "°F", "TB": "°F"]))
    verifyNum(comp(g, "k")["out"], 0.5f, null)
    verifyNum(comp(g, "gre_t")["out"], 1.8f, "Δ°F")
  }

  ** Wrong behaviour caught: a difference unit taken for an absolute
  ** connector, an absolute unit for a difference, or a point unit for a
  ** connector its condition removed, accepted (S2, N4); and a difference
  ** connector in a converted group not told its point unit.
  Void testPointUnitContract()
  {
    verifyRefuses(["TA is not declared a difference", "Δ°F"], |->Obj?| { return resolve(lib, "G5", Etc.dict1("r", Number(1f)), pu(["TA": "Δ°F"])) })
    verifyRefuses(["dT is a temperature difference", "Δ°F"], |->Obj?| { return resolve(lib, "G5", Etc.dict1("r", Number(1f)), pu(["TA": "°F", "dT": "°F"])) })
    verifyRefuses(["TOld is removed by its condition"], |->Obj?| { return resolve(lib, "G5", Etc.dict1("r", Number(1f)), pu(["TOld": "°F"])) })
    g := resolve(lib, "G5", Etc.dict1("r", Number(1f)), pu(["TA": "°F"]))
    verifyEq(comp(g, "dT")["pointUnit"], "Δ°F")
    verifyEq(comp(g, "y")["pointUnit"], "°F")
    verifyEq(comp(g, "tA")["pointUnit"], "°F")
  }

  ** Wrong behaviour caught: a missing parameter reported as a cycle of
  ** defaults, or a binding that reads a disabled parameter reported as an
  ** unknown name with no reason (S3).
  Void testRefusalsNameTheirCause()
  {
    verifyRefuses(["parameter r has no default and no value", "the default of b reads it"], |->Obj?| { return resolve(lib, "G5") })
    verifyRefuses(["reads q", "enable condition (not mode) is false"], |->Obj?| { return resolve(lib, "G6") })
  }

  ** Wrong behaviour caught: a literal marked a difference converted without
  ** the offset although its kind group is absolute, which puts the 280 K
  ** threshold at 504 Δ°F (S4).
  Void testStatedKindMustAgree()
  {
    verifyRefuses(["les_t.out", "absolute temperatures and differences"], |->Obj?| { return resolve(lib, "G7", Etc.dict0, pu(["TA": "°F"])) })
  }

  ** Wrong behaviour caught: a conversion that is exact on paper written
  ** with float error, which flips a comparison at its boundary (N1).
  Void testConversionsAreTidy()
  {
    g := resolve(lib, "G4", Etc.dict0, pu(["TA": "°F", "TB": "°F"]))
    verifyEq(num(comp(g, "gre_t")["out"]).toFloat, 1.8f)
  }

  ** Wrong behaviour caught (B1, on the libraries): SZ's fan-speed curve
  ** breakpoints, dimensionless loop signals, stretched by 1.8 under °F, and
  ** the damper-closed alarm threshold of a terminal unit written as a flow.
  Void testLibraryDomainsStaySeparate()
  {
    sz := "kw.cdl.g36.ahu::AhusSingleZoneVavController"
    ns2 := XetoEnv.cur.resolveNamespace(["kw.cdl.g36.terminal", "kw.cdl.g36.ahu"])
    p := Etc.dict2("eneStd", "ASHRAE90_1", "venStd", "ASHRAE62_1")
    temps := Str:Obj[:]
    ns2.spec(sz).slots.each |s| { if ((s.meta.has("cdlInput") || s.meta.has("cdlOutput")) && s.meta["cdlUnit"] == "K" && s.meta["cdlCondition"] == null) temps[s.meta["cdlName"].toStr] = s.meta.has("cdlDelta") ? "Δ°F" : "°F" }
    si := CdlResolver(ns2).resolve(sz, p)
    f := CdlResolver(ns2).resolve(sz, p, Etc.dict1("pointUnits", Etc.makeDict(temps)))
    found := 0
    Etc.dictNames(si).each |n|
    {
      d := si[n] as Dict
      if (d == null || !n.startsWith("setPoiVAV_supTemSet_tem") || !n.contains("Poi")) return
      v := (d["out"] as StatusNumber)?.num
      if (v == null) return
      found++
      verify([0.75f, 0.5f, 0.25f].contains(v.toFloat), n + " = " + v)
      verifyEq(v.unit, null, n + " in SI")
      verifyEq(((Dict)f[n])["out"], d["out"], n + " under °F")
    }
    verify(found >= 4, "the fan-speed breakpoints were not found ($found)")

    co := "kw.cdl.g36.terminal::TerminalUnitsCoolingOnlyController"
    cp := Etc.makeDict(["venStd": "ASHRAE62_1", "VCooMax_flow": Number(0.5f), "VMin_flow": Number(0.1f), "VAreBreZon_flow": Number(0.03f), "VPopBreZon_flow": Number(0.02f)])
    t := CdlResolver(ns2).resolve(co, cp, Etc.dict1("pointUnits", Etc.dict1("VDis_flow", "cfm")))
    verifyEq(((StatusNumber)((Dict)t["ala_cloDam_t"])["out"]).num, Number(0.005f))
  }

  ** Wrong behaviour caught: two point units in one unit group accepted, so
  ** one of the two points is read in the other's unit.
  Void testTwoPointUnitsInOneGroupRefuse()
  {
    verifyRefuses(["reaches points in", "°F", "°C"], |->Obj?| { return resolve(lib, "G8", Etc.dict0, pu(["TA": "°F", "TB": "°C"])) })
  }

  ** Wrong behaviour caught: the difference of two absolute temperatures
  ** graded absolute, so an unmarked 2 K threshold on it converts with the
  ** offset (-456.07 °F) rather than as 3.6 Δ°F; and an unmarked K literal
  ** forced absolute rather than read from its group.
  Void testDifferenceOfTwoTemperatures()
  {
    g := resolve(lib, "G9", Etc.dict0, pu(["TA": "°F", "TB": "°F"]))
    verifyNum(comp(g, "gre_t")["out"], 3.6f, "Δ°F")
  }

  ** Wrong behaviour caught: the product of two dimensionless signals left
  ** of unknown unit, so a kelvin threshold compared with it is accepted
  ** rather than refused as a conflict.
  Void testDimensionlessProductIsDerived()
  {
    verifyRefuses(["mixes the units", "1", "K"], |->Obj?| { return resolve(lib, "G10") })
  }

  ** Wrong behaviour caught: a nested composite connector's unit dropped on
  ** the way, so a literal its group reads is written with no unit.
  Void testConnectorUnitsReachTheirGroup()
  {
    g := resolve(lib, "G11")
    verifyNum(comp(g, "inn_gre_t")["out"], 5f, "Pa")
  }

  ** Wrong behaviour caught: a product of a temperature and a flow accepted
  ** under °F, though its result has no unit to convert into.
  Void testProductOfUnitsInConvertedGroupRefuses()
  {
    resolve(lib, "G12")
    verifyRefuses(["pro", "mul of values in K and m³/s", "converted"], |->Obj?| { return resolve(lib, "G12", Etc.dict0, pu(["TA": "°F"])) })
  }

  ** Wrong behaviour caught: the product of two dimensionless signals left
  ** of unknown unit, so a constant it shares with another dimensionless
  ** signal is split into needless copies.
  Void testProductOfDimensionlessIsDimensionless()
  {
    g := resolve(lib, "G13")
    verifyEq(compNames(g).findAll { it.startsWith("k") }, ["k"])
  }

  ** Wrong behaviour caught: a product whose output and one dimensionless
  ** input are known leaving its other input's unit unknown, so a literal
  ** compared with that input is written with no unit.
  Void testProductInfersItsOtherInput()
  {
    g := resolve(lib, "G14")
    verifyNum(comp(g, "gre2_t")["out"], 3f, "K")
  }
}
