//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Parameters: defaults in dependency order, required values, enable
** conditions, given units and bounds
**
class ParamsTest : ResolveTestBase
{
  static const Str src :=
    Str<|P1: kw.cdl::CdlBlock {
           a: Number? <cdlParam, cdlName:"a", cdlType:"Real"> "1"
           b: Number? <cdlParam, cdlName:"b", cdlType:"Real", cdlDefault:"2*c">
           c: Number? <cdlParam, cdlName:"c", cdlType:"Real", cdlDefault:"a+1">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"b"}>
         }
         P2: kw.cdl::CdlBlock {
           b: Number? <cdlParam, cdlName:"b", cdlType:"Real", cdlDefault:"c">
           c: Number? <cdlParam, cdlName:"c", cdlType:"Real", cdlDefault:"b">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"b"}>
         }
         P3: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "false"
           q: Number <cdlParam, cdlName:"q", cdlType:"Real", cdlEnable:"mode">
           r: Number <cdlParam, cdlName:"r", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"r"}>
         }
         P4: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "false"
           t: Number? <cdlParam, cdlName:"T", cdlType:"Real", cdlUnit:"K", quantity:"temperature", cdlSiMin:"273.15K"> "280"
           d: Number? <cdlParam, cdlName:"dT", cdlType:"Real", cdlUnit:"K", cdlDelta> "1"
           n: Number? <cdlParam, cdlName:"n", cdlType:"Real", minVal:"0", cdlMinWhen:List {kw.cdl::CdlBoundWhen {val:Number "5", cond:"mode", via:"x.n"}}> "1"
           yT: hx.comps::StatusNumber? <cdlOutput, cdlName:"yT", cdlType:"Real", cdlUnit:"K", quantity:"temperature", transient, readonly, link:"kT.out">
           yD: hx.comps::StatusNumber? <cdlOutput, cdlName:"yD", cdlType:"Real", cdlUnit:"K", cdlDelta, transient, readonly, link:"kD.out">
           kT: hx.comps::NumberConst? <cdlInstance, cdlName:"kT", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"T"}>
           kD: hx.comps::NumberConst? <cdlInstance, cdlName:"kD", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"dT"}>
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  ** Wrong behaviour caught: defaults evaluated in declaration order, so b
  ** reads c before c exists, or a given value not taking precedence over
  ** its default.
  Void testDefaultsInDependencyOrder()
  {
    g := resolve(lib, "P1", Etc.dict1("a", Number(3f)))
    verifyNum(comp(g, "k")["out"], 8f, null)
    g = resolve(lib, "P1", Etc.dict0)
    verifyNum(comp(g, "k")["out"], 4f, null)
  }

  ** Wrong behaviour caught: two defaults that read each other looping, or
  ** one of them silently taking 0.
  Void testCycleRefuses()
  {
    verifyRefuses(["b", "c", "cycle"], |->Obj?| { return resolve(lib, "P2") })
  }

  ** Wrong behaviour caught: a missing required parameter defaulting to 0,
  ** or a parameter its enable condition switches off still being demanded.
  Void testRequiredAndEnable()
  {
    verifyRefuses(["parameter r has no default and no value"], |->Obj?| { return resolve(lib, "P3") })
    g := resolve(lib, "P3", Etc.dict1("r", Number(2f)))
    verifyNum(comp(g, "k")["out"], 2f, null)
    verifyRefuses(["parameter q has no default and no value"], |->Obj?| { return resolve(lib, "P3", Etc.dict2("r", Number(2f), "mode", true)) })
  }

  ** Wrong behaviour caught: an unknown name, the Xeto slot name in place
  ** of the CDL name, or a value of the wrong type accepted.
  Void testGivenNamesAndTypes()
  {
    verifyRefuses(["nope is not a parameter"], |->Obj?| { return resolve(lib, "P1", Etc.dict1("nope", Number(1f))) })
    verifyRefuses(["t is not a parameter", "its CDL name is T"], |->Obj?| { return resolve(lib, "P4", Etc.dict1("t", Number(1f))) })
    verifyRefuses(["parameter mode is a Boolean"], |->Obj?| { return resolve(lib, "P3", Etc.dict2("r", Number(1f), "mode", Number(1f))) })
  }

  ** Wrong behaviour caught: a Fahrenheit value taken as kelvin, an absolute
  ** temperature converted without the offset, or a difference converted
  ** with it.
  Void testGivenUnitsConvertToSi()
  {
    g := resolve(lib, "P4", Etc.dict2("T", Number(50f, Unit("°F")), "dT", Number(1.8f, Unit("Δ°F"))))
    verifyNum(comp(g, "kT")["out"], 283.15f, "K")
    verifyNum(comp(g, "kD")["out"], 1f, "K")
  }

  ** Wrong behaviour caught: an SI bound compared against the value before
  ** conversion, a guarded bound ignored when its condition holds, or applied
  ** when it does not.
  Void testBounds()
  {
    verifyRefuses(["parameter T", "below its minimum 273.15"], |->Obj?| { return resolve(lib, "P4", Etc.dict1("T", Number(30f, Unit("°F")))) })
    verifyRefuses(["parameter n", "below its minimum 0"], |->Obj?| { return resolve(lib, "P4", Etc.dict1("n", Number(-1f))) })
    resolve(lib, "P4", Etc.dict1("n", Number(2f)))
    verifyRefuses(["parameter n = 2", "below its minimum 5", "when mode", "x.n"], |->Obj?| { return resolve(lib, "P4", Etc.dict2("n", Number(2f), "mode", true)) })
  }

  ** Wrong behaviour caught: an absolute temperature given as a difference
  ** (70 Δ°F) converted with no offset to 38.9 K.
  Void testAbsoluteGivenAsDifferenceRefuses()
  {
    verifyRefuses(["parameter T is an absolute value", "a difference"], |->Obj?| { return resolve(lib, "P4", Etc.dict1("T", Number(70f, Unit("Δ°F")))) })
  }
}
