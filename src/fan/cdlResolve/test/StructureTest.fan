//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Conditions, alternative links, bindings and their conversions, the
** compound gain, Logical.Pre seeds and flattening
**
class StructureTest : ResolveTestBase
{
  static const Str src :=
    Str<|C1: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "true"
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"a1.out", cdlAltLink:"a1.out,a2.out">
           z: hx.comps::StatusNumber? <cdlOutput, cdlName:"z", cdlType:"Real", cdlCondition:"mode", transient, readonly, link:"a1.out">
           a1: hx.comps::AbsValue? <cdlInstance, cdlName:"a1", cdlOf:@kw.cdl::cdl-RealsAbs, cdlCondition:"mode"> { inA: <link:"u"> }
           a2: hx.comps::AbsValue? <cdlInstance, cdlName:"a2", cdlOf:@kw.cdl::cdl-RealsAbs, cdlCondition:"not mode"> { inA: <link:"u"> }
         }
         C2: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, cdlAltLink:"a1.out,a2.out">
           a1: hx.comps::AbsValue? <cdlInstance, cdlName:"a1", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"u"> }
           a2: hx.comps::AbsValue? <cdlInstance, cdlName:"a2", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"u"> }
         }
         B1: kw.cdl::CdlBlock {
           delay: Number? <cdlParam, cdlName:"delay", cdlType:"Real", cdlUnit:"s", quantity:"time", unit:"sec"> "120"
           u: hx.comps::StatusBool? <cdlInput, cdlName:"u", cdlType:"Boolean">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"tru.out">
           tru: hx.comps::BoolDelay? <cdlInstance, cdlName:"tru", cdlOf:@kw.cdl::cdl-LogicalTrueDelay, cdlBind:{delayTime:"delay"}> { in: <link:"u"> }
           pid: hx.comps::CdlPid? <cdlInstance, cdlName:"pid", cdlOf:@kw.cdl::cdl-RealsPid, cdlBind:{controllerType:"Buildings.Controls.OBC.CDL.Types.SimpleController.P", k:"0.5", ti:"delay*2.5"}>
         }
         B2: kw.cdl::CdlBlock {
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"abs.out">
           abs: hx.comps::AbsValue? <cdlInstance, cdlName:"abs", cdlOf:@kw.cdl::cdl-RealsAbs, cdlBind:{k:"1"}>
         }
         S1: kw.cdl::CdlBlock {
           u: hx.comps::StatusBool? <cdlInput, cdlName:"u", cdlType:"Boolean">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"lat.out">
           lat: hx.comps::SetResetLatch? <cdlInstance, cdlName:"lat", cdlOf:@kw.cdl::cdl-LogicalLatch> {
             in: <link:"u">
             inClear: <link:"not1.out", loopCut, cdlLinkVia:"pre1">
           }
           not1: hx.comps::Not? <cdlInstance, cdlName:"not1", cdlOf:@kw.cdl::cdl-LogicalNot> { in: <link:"lat.out"> }
           pre1: kw.cdl::CdlWire? <cdlInstance, cdlName:"pre1", cdlOf:@kw.cdl::cdl-LogicalPre, cdlBind:{pre_u_start:"true"}>
         }
         F1: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"a.out">
           a: hx.comps::AbsValue? <cdlInstance, cdlName:"a", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"u"> }
         }
         F2: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"inn.y">
           z: hx.comps::StatusNumber? <cdlOutput, cdlName:"z", cdlType:"Real", transient, readonly, link:"neg.out">
           inn: F1? <cdlInstance, cdlName:"inn"> { u: <link:"u"> }
           neg: hx.comps::Negative? <cdlInstance, cdlName:"neg", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"inn.y"> }
         }
         F3: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           inn: F1? <cdlInstance, cdlName:"inn"> { u: <link:"u"> }
           inn_a: hx.comps::AbsValue? <cdlInstance, cdlName:"inn_a", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"u"> }
         }
         F4: kw.cdl::CdlBlock {
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"inn.y">
           inn: F1? <cdlInstance, cdlName:"inn">
         }
         S2: kw.cdl::CdlBlock {
           u: hx.comps::StatusBool? <cdlInput, cdlName:"u", cdlType:"Boolean">
           y: hx.comps::StatusBool? <cdlOutput, cdlName:"y", cdlType:"Boolean", transient, readonly, link:"lat.out">
           lat: hx.comps::SetResetLatch? <cdlInstance, cdlName:"lat", cdlOf:@kw.cdl::cdl-LogicalLatch> {
             in: <link:"u">
             inClear: <link:"not1.out", loopCut, cdlLinkVia:"pre1">
           }
           not1: hx.comps::Not? <cdlInstance, cdlName:"not1", cdlOf:@kw.cdl::cdl-LogicalNot> { in: <link:"lat.out"> }
           pre1: kw.cdl::CdlWire? <cdlInstance, cdlName:"pre1", cdlOf:@kw.cdl::cdl-LogicalPre>
         }
         C3: kw.cdl::CdlBlock {
           mode: Bool? <cdlParam, cdlName:"mode", cdlType:"Boolean"> "true"
           u: hx.comps::StatusNumber? <cdlInput, cdlName:"u", cdlType:"Real">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"a1.out", cdlAltLink:"a1.out,a2.out">
           a1: hx.comps::AbsValue? <cdlInstance, cdlName:"a1", cdlOf:@kw.cdl::cdl-RealsAbs, cdlCondition:"mode and false"> { inA: <link:"u"> }
           a2: hx.comps::AbsValue? <cdlInstance, cdlName:"a2", cdlOf:@kw.cdl::cdl-RealsAbs, cdlCondition:"not mode"> { inA: <link:"u"> }
         }
         P5: kw.cdl::CdlBlock {
           n: Number? <cdlParam, cdlName:"n", cdlType:"Real"> "1"
           q: Number <cdlParam, cdlName:"q", cdlType:"Real", cdlEnable:"n">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"k.out">
           k: hx.comps::NumberConst? <cdlInstance, cdlName:"k", cdlOf:@kw.cdl::cdl-RealsSourcesConstant, cdlBind:{k:"n"}>
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  ** Wrong behaviour caught: a child whose condition is false still emitted,
  ** an output of a removed connector still emitted, or the alternative
  ** driver chosen by order instead of by presence.
  Void testConditionsAndAltLinks()
  {
    g := resolve(lib, "C1")
    verifyEq(compNames(g), ["a1", "u", "y", "z"])
    verifyEq(linkOf(g, "y", "in"), "a1.out")
    g = resolve(lib, "C1", Etc.dict1("mode", false))
    verifyEq(compNames(g), ["a2", "u", "y"])
    verifyEq(linkOf(g, "y", "in"), "a2.out")
    verifyRefuses(["output connector y", "more than one of its alternative drivers", "a1.out, a2.out"], |->Obj?| { return resolve(lib, "C2") })
  }

  ** Wrong behaviour caught: a seconds value written to a Duration slot as a
  ** bare number, an enumeration key not mapped to the comp's key, a Float
  ** slot given a Number, a class's fixed slot left at the comp default
  ** (offDelay 1sec), or a binding naming no parameter accepted.
  Void testBindingsAndConversions()
  {
    g := resolve(lib, "B1", Etc.dict1("delay", Number(60f)))
    verifyEq(comp(g, "tru")["onDelay"], 1min)
    verifyEq(comp(g, "tru")["offDelay"], 0sec)
    verifyEq(comp(g, "pid")["controllerType"].toStr, "p")
    verifyEq(comp(g, "pid")["k"], 0.5f)
    verifyEq(comp(g, "pid")["ti"], 150sec)
    verifyRefuses(["abs: the binding k is not a parameter", "Reals.Abs"], |->Obj?| { return resolve(lib, "B2") })
  }

  ** Wrong behaviour caught: a Pre seed left off, so a latch loop starts
  ** null; the seed written as false when pre_u_start is true; or the cut
  ** link losing its loopCut marker.
  Void testPreSeed()
  {
    g := resolve(lib, "S1")
    verifyEq(((StatusBool)comp(g, "lat")["inClear"]).bool, true)
    links := comp(g, "lat")["links"] as Links
    verifyEq(links.listOn("inClear").first["loopCut"], Marker.val)
    verifyEq(links.listOn("in").first["loopCut"], null)
    cs := load(g)
    (cs.root.get("u") as Comp).set("curVal", StatusBool(false, Status.ok))
    execute(cs)
    // seeded, the loop through the cut has a value on the first execute
    verifyNotNull((cs.root.get("lat") as Comp).get("out"))
  }

  ** Wrong behaviour caught: a nested composite left as a comp, a composite
  ** slot left on the path so a value waits a cycle per boundary, or a comp
  ** named by its leaf so two instances collide.
  Void testFlatten()
  {
    g := resolve(lib, "F2")
    verifyEq(compNames(g), ["inn_a", "neg", "u", "y", "z"])
    verifyEq(comp(g, "inn_a")["cdlPath"], "inn.a")
    verifyEq(comp(g, "inn_a")["spec"], Ref("hx.comps::AbsValue"))
    verifyEq(linkOf(g, "inn_a", "inA"), "u.curVal")
    verifyEq(linkOf(g, "neg", "inA"), "inn_a.out")
    verifyEq(linkOf(g, "y", "in"), "inn_a.out")
    cs := load(g)
    (cs.root.get("u") as Comp).set("curVal", StatusNumber(Number(-3f), Status.ok))
    execute(cs)
    verifyEq(((StatusNumber)(cs.root.get("z") as Comp).get("in")).num, Number(-3f))
    verifyEq(((Comp)cs.root.get("inn_a")).id, Ref("cdl-inn_a"))
  }

  ** Wrong behaviour caught: two instance paths flattening to one name, the
  ** second silently replacing the first.
  Void testNameCollisionRefuses()
  {
    verifyRefuses(["inn.a", "inn_a", "both flatten"], |->Obj?| { return resolve(lib, "F3") })
  }

  ** Wrong behaviour caught: a nested composite's input that nothing drives
  ** left as an unlinked comp slot, which CDL forbids and the root refuses.
  Void testUndrivenNestedInputRefuses()
  {
    verifyRefuses(["inn.u", "nothing drives"], |->Obj?| { return resolve(lib, "F4") })
  }

  ** Wrong behaviour caught: a Pre with no pre_u_start seeding true, where
  ** CDL's default is false.
  Void testPreSeedDefaultsFalse()
  {
    g := resolve(lib, "S2")
    verifyEq(((StatusBool)comp(g, "lat")["inClear"]).bool, false)
  }

  ** Wrong behaviour caught: a sink none of whose alternative drivers is
  ** present falling back to its primary link instead of refusing.
  Void testNoAlternativePresentRefuses()
  {
    verifyRefuses(["output connector y", "none of its alternative drivers is present"], |->Obj?| { return resolve(lib, "C3") })
  }

  ** Wrong behaviour caught: an enable condition that is not a Boolean read
  ** as false, so a required parameter is silently exempted.
  Void testEnableMustBeBoolean()
  {
    verifyRefuses(["parameter q"], |->Obj?| { return resolve(lib, "P5") })
  }
}
