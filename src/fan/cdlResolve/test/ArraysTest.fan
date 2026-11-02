//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using hxComps

**
** Array expansion: vector connectors, reduction trees, gains, masks and
** constant matrices
**
class ArraysTest : ResolveTestBase
{
  static const Str src :=
    Str<|A1: kw.cdl::CdlBlock <cdlExpand> {
           n: Int? <cdlParam, cdlName:"n", cdlType:"Integer"> "6"
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(n)">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"mm.y">
           mm: kw.cdl::RealsMultiMax? <cdlInstance, cdlName:"mm", cdlOf:@kw.cdl::cdl-RealsMultiMax, cdlBind:{nin:"n"}> { u: <link:"u"> }
         }
         A2: kw.cdl::CdlBlock <cdlExpand> {
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(4)">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"ms.y">
           ms: kw.cdl::RealsMultiSum? <cdlInstance, cdlName:"ms", cdlOf:@kw.cdl::cdl-RealsMultiSum, cdlBind:{nin:"4", k:"{1,-1,0,2}"}> { u: <link:"u"> }
         }
         A3: kw.cdl::CdlBlock <cdlExpand> {
           nout: Int? <cdlParam, cdlName:"nout", cdlType:"Integer"> "2"
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(3)">
           y: List? <cdlOutput, cdlName:"y", cdlType:"Real", cdlArraySize:"(nout)", transient, readonly, link:"fil.y">
           fil: kw.cdl::RoutingRealVectorFilter? <cdlInstance, cdlName:"fil", cdlOf:@kw.cdl::cdl-RoutingRealVectorFilter, cdlBind:{nin:"3", nout:"nout", msk:"{true,false,true}"}> { u: <link:"u"> }
         }
         A4: kw.cdl::CdlBlock <cdlExpand> {
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(3)">
           y: List? <cdlOutput, cdlName:"y", cdlType:"Real", cdlArraySize:"(2)", transient, readonly, link:"gai.y">
           gai: kw.cdl::RealsMatrixGain? <cdlInstance, cdlName:"gai", cdlOf:@kw.cdl::cdl-RealsMatrixGain, cdlBind:{k:"[0,1,0;1,0,1]"}> { u: <link:"u"> }
         }
         A5: kw.cdl::CdlBlock <cdlExpand> {
           n: Int? <cdlParam, cdlName:"n", cdlType:"Integer"> "3"
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(n)">
           y: List? <cdlOutput, cdlName:"y", cdlType:"Real", cdlArraySize:"(n)", transient, readonly, link:"abs.out">
           abs: hx.comps::AbsValue? <cdlInstance, cdlName:"abs", cdlOf:@kw.cdl::cdl-RealsAbs, cdlArraySize:"(n)"> { inA: <link:"u"> }
         }
         A6: kw.cdl::CdlBlock <cdlExpand> {
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(2)">
           y1: hx.comps::StatusNumber? <cdlOutput, cdlName:"y1", cdlType:"Real", transient, readonly, link:"a1.out">
           y2: hx.comps::StatusNumber? <cdlOutput, cdlName:"y2", cdlType:"Real", transient, readonly, link:"a2.out">
           mm: kw.cdl::RealsMultiMax? <cdlInstance, cdlName:"mm", cdlOf:@kw.cdl::cdl-RealsMultiMax, cdlBind:{nin:"2"}> { u: <link:"u"> }
           a1: hx.comps::AbsValue? <cdlInstance, cdlName:"a1", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"mm.y", loopCut> }
           a2: hx.comps::AbsValue? <cdlInstance, cdlName:"a2", cdlOf:@kw.cdl::cdl-RealsAbs> { inA: <link:"mm.y"> }
         }
         A7: kw.cdl::CdlBlock <cdlExpand> {
           byRow: Bool? <cdlParam, cdlName:"byRow", cdlType:"Boolean"> "true"
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(2,3)">
           y: List? <cdlOutput, cdlName:"y", cdlType:"Real", cdlArraySize:"(if byRow then 2 else 3)", transient, readonly, link:"mx.y">
           mx: kw.cdl::RealsMatrixMax? <cdlInstance, cdlName:"mx", cdlOf:@kw.cdl::cdl-RealsMatrixMax, cdlBind:{nRow:"2", nCol:"3", rowMax:"byRow"}> { u: <link:"u"> }
         }
         A8: kw.cdl::CdlBlock <cdlExpand> {
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(2)">
           idx: hx.comps::StatusNumber? <cdlInput, cdlName:"idx", cdlType:"Integer">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"ext.y">
           ext: kw.cdl::RoutingRealExtractor? <cdlInstance, cdlName:"ext", cdlOf:@kw.cdl::cdl-RoutingRealExtractor, cdlBind:{nin:"2"}> { u: <link:"u">, index: <link:"idx"> }
         }
         A9: kw.cdl::CdlBlock <cdlExpand> {
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(2)">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"ms.y">
           ms: kw.cdl::RealsMultiSum? <cdlInstance, cdlName:"ms", cdlOf:@kw.cdl::cdl-RealsMultiSum, cdlBind:{nin:"2", k:"{1,2}"}> { u: <link:"u"> }
           ms_k2: hx.comps::NumberConst? <cdlInstance, cdlName:"ms_k2", cdlOf:@kw.cdl::cdl-RealsSourcesConstant> { out: hx.comps::StatusNumber { val: 7 } }
         }
         A10: kw.cdl::CdlBlock <cdlExpand> {
           n: Int? <cdlParam, cdlName:"n", cdlType:"Integer"> "3"
           k: List? <cdlParam, cdlName:"k", cdlType:"Real", cdlArraySize:"(n)", cdlDefault:"fill(1, n)">
           u: List? <cdlInput, cdlName:"u", cdlType:"Real", cdlArraySize:"(n)">
           y: hx.comps::StatusNumber? <cdlOutput, cdlName:"y", cdlType:"Real", transient, readonly, link:"ms.y">
           ms: kw.cdl::RealsMultiSum? <cdlInstance, cdlName:"ms", cdlOf:@kw.cdl::cdl-RealsMultiSum, cdlBind:{nin:"n", k:"k"}> { u: <link:"u"> }
         }
         |>

  Lib lib() { if (libRef == null) libRef = temp(src); return libRef }
  private Lib? libRef

  ** Wrong behaviour caught: a reduction over more than four inputs built as
  ** one comp that drops the fifth, leaves taken out of index order, or the
  ** tree's levels misnamed so ids change between resolves.
  Void testReduceTree()
  {
    g := resolve(lib, "A1")
    verifyEq(compNames(g), ["mm_L1_1", "mm_L1_2", "mm_L2_1", "u_1", "u_2", "u_3", "u_4", "u_5", "u_6", "y"])
    verifyEq(linkOf(g, "mm_L1_1", "inA"), "u_1.curVal")
    verifyEq(linkOf(g, "mm_L1_1", "inD"), "u_4.curVal")
    verifyEq(linkOf(g, "mm_L1_2", "inA"), "u_5.curVal")
    verifyEq(linkOf(g, "mm_L1_2", "inB"), "u_6.curVal")
    verifyEq(linkOf(g, "mm_L1_2", "inC"), null)
    verifyEq(linkOf(g, "mm_L2_1", "inA"), "mm_L1_1.out")
    verifyEq(linkOf(g, "y", "in"), "mm_L2_1.out")
    verifyEq(comp(g, "mm_L1_1")["spec"], Ref("hx.comps::Maximum"))
    cs := load(g)
    [3f, -1f, 7f, 2f, 9f, 4f].each |v, i| { (cs.root.get("u_${i+1}") as Comp).set("curVal", StatusNumber(Number(v), Status.ok)) }
    execute(cs)
    verifyEq(((StatusNumber)(cs.root.get("y") as Comp).get("in")).num, Number(9f))
  }

  ** Wrong behaviour caught: one input still wrapped in a comp, or no input
  ** given a value instead of a refusal.
  Void testReduceEdges()
  {
    g := resolve(lib, "A1", Etc.dict1("n", Number(1f)))
    verifyEq(compNames(g), ["u_1", "y"])
    verifyEq(linkOf(g, "y", "in"), "u_1.curVal")
    verifyRefuses(["mm", "over no inputs"], |->Obj?| { return resolve(lib, "A1", Etc.dict1("n", Number(0f))) })
  }

  ** Wrong behaviour caught: MultiSum gains ignored, a gain of 0 kept as a
  ** term, or -1 built as a multiply.
  Void testSumGains()
  {
    g := resolve(lib, "A2")
    verifyEq(linkOf(g, "ms_neg_2", "inA"), "u_2.curVal")
    verifyEq(linkOf(g, "ms_gain_4", "inA"), "u_4.curVal")
    verifyEq(linkOf(g, "ms_gain_4", "inB"), "ms_k2.out")
    verifyEq(linkOf(g, "ms_L1_1", "inA"), "u_1.curVal")
    verifyEq(linkOf(g, "ms_L1_1", "inB"), "ms_neg_2.out")
    verifyEq(linkOf(g, "ms_L1_1", "inC"), "ms_gain_4.out")
    verifyEq(linkOf(g, "ms_L1_1", "inD"), null)
    cs := load(g)
    [1f, 2f, 100f, 3f].each |v, i| { (cs.root.get("u_${i+1}") as Comp).set("curVal", StatusNumber(Number(v), Status.ok)) }
    execute(cs)
    verifyEq(((StatusNumber)(cs.root.get("y") as Comp).get("in")).num.toFloat, 5f)
  }

  ** Wrong behaviour caught: a mask picking the wrong elements, or a mask
  ** whose true count differs from nout accepted.
  Void testVectorFilter()
  {
    g := resolve(lib, "A3")
    verifyEq(linkOf(g, "y_1", "in"), "u_1.curVal")
    verifyEq(linkOf(g, "y_2", "in"), "u_3.curVal")
    verifyRefuses(["fil", "msk selects 2 elements; nout is 3"], |->Obj?| { return resolve(lib, "A3", Etc.dict1("nout", Number(3f))) })
  }

  ** Wrong behaviour caught: a zero matrix entry kept, a row of one unit
  ** entry wrapped in a comp, or rows and columns swapped.
  Void testMatrixGain()
  {
    g := resolve(lib, "A4")
    verifyEq(linkOf(g, "y_1", "in"), "u_2.curVal")
    verifyEq(linkOf(g, "y_2", "in"), "gai_r2_L1_1.out")
    verifyEq(linkOf(g, "gai_r2_L1_1", "inA"), "u_1.curVal")
    verifyEq(linkOf(g, "gai_r2_L1_1", "inB"), "u_3.curVal")
  }

  ** Wrong behaviour caught: a vectorized instance not expanded per element,
  ** or element k linked to another element's driver.
  Void testVectorizedInstance()
  {
    g := resolve(lib, "A5")
    verifyEq(compNames(g), ["abs_1", "abs_2", "abs_3", "u_1", "u_2", "u_3", "y_1", "y_2", "y_3"])
    verifyEq(comp(g, "abs_2")["cdlPath"], "abs[2]")
    verifyEq(linkOf(g, "abs_3", "inA"), "u_3.curVal")
    verifyEq(linkOf(g, "y_2", "in"), "abs_2.out")
  }

  ** Wrong behaviour caught: one reader's loopCut written onto the shared
  ** output of an expanded array instance, so every other reader of it is
  ** cut too and waits a cycle.
  Void testArrayOutputSharedByReaders()
  {
    g := resolve(lib, "A6")
    verifyEq((comp(g, "a1")["links"] as Links).listOn("inA").first["loopCut"], Marker.val)
    verifyEq((comp(g, "a2")["links"] as Links).listOn("inA").first["loopCut"], null)
  }

  ** Wrong behaviour caught: MatrixMax reducing columns where rowMax asks
  ** for rows, or rows where it asks for columns.
  Void testMatrixMaxRowsAndColumns()
  {
    g := resolve(lib, "A7")
    verifyEq(linkOf(g, "y_1", "in"), "mx_r1_L1_1.out")
    verifyEq(linkOf(g, "mx_r1_L1_1", "inA"), "u_1_1.curVal")
    verifyEq(linkOf(g, "mx_r1_L1_1", "inC"), "u_1_3.curVal")
    c := resolve(lib, "A7", Etc.dict1("byRow", false))
    verifyEq(linkOf(c, "y_3", "in"), "mx_c3_L1_1.out")
    verifyEq(linkOf(c, "mx_c3_L1_1", "inA"), "u_1_3.curVal")
    verifyEq(linkOf(c, "mx_c3_L1_1", "inB"), "u_2_3.curVal")
  }

  ** Wrong behaviour caught: an Extractor over two inputs left with its third
  ** select slot unlinked, so an index of 3 or more gives null where CDL
  ** clamps to u[2].
  Void testExtractorClampsAtTwo()
  {
    g := resolve(lib, "A8")
    verifyEq(comp(g, "ext_sel")["numInputs"], 3)
    verifyEq(linkOf(g, "ext_sel", "inC"), "u_2.curVal")
    cs := load(g)
    (cs.root.get("u_1") as Comp).set("curVal", StatusNumber(Number(10f), Status.ok))
    (cs.root.get("u_2") as Comp).set("curVal", StatusNumber(Number(20f), Status.ok))
    (cs.root.get("idx") as Comp).set("curVal", StatusNumber(Number(5f), Status.ok))
    execute(cs)
    verifyEq(((StatusNumber)(cs.root.get("y") as Comp).get("in")).num, Number(20f))
  }

  ** Wrong behaviour caught: an expansion's shared constant reusing a child
  ** comp that happens to carry the same name (N3).
  Void testConstantNameClashRefuses()
  {
    verifyRefuses(["ms_k2", "clashes"], |->Obj?| { return resolve(lib, "A9") })
  }

  ** Wrong behaviour caught: an array parameter whose length differs from its
  ** size accepted, so a gain is read past the end or dropped.
  Void testArrayParameterShapeChecked()
  {
    verifyRefuses(["parameter k has shape", "its size (n) gives"], |->Obj?| { return resolve(lib, "A10", Etc.dict1("k", Obj?[Number(1f), Number(2f)])) })
  }
}
