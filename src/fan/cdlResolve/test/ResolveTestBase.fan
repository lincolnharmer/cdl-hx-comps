//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using concurrent
using xeto
using haystack
using hxComps

**
** Shared helpers: a namespace holding hx.comps and kw.cdl, small composites
** compiled from source, and a comp space to run a resolved graph in. The
** tests need the kw.cdl libs, and the G36 libs for the cases that name them,
** on the environment's path.
**
abstract class ResolveTestBase : Test
{
  static const Str header :=
    Str<|pragma: Lib <
           version: "0.0.1"
           depends: { { lib: "sys" }, { lib: "sys.comp" }, { lib: "hx.comps" }, { lib: "kw.cdl" } }
         >
         |>

  Namespace ns()
  {
    if (nsRef == null) nsRef = XetoEnv.cur.resolveNamespace(["kw.cdl.g36.common", "kw.cdl", "hx.comps"])
    return nsRef
  }
  private Namespace? nsRef

  ** Compile composites from Xeto source into a temp lib
  Lib temp(Str src) { ns.compileTempLib(header + src) }

  ** Resolve one composite of a temp lib
  Dict resolve(Lib lib, Str name, Dict params := Etc.dict0, Dict? opts := null)
  {
    CdlResolver(ns).resolveSpec(lib.spec(name), params, opts)
  }

  ** Verify a resolve refuses with a message holding every fragment
  Void verifyRefuses(Str[] frags, |->Obj?| f)
  {
    try { f(); fail("resolved, and a refusal naming " + frags + " was expected") }
    catch (CdlResolveErr e) { frags.each |s| { verify(e.msg.contains(s), "refusal does not name '$s': $e.msg") } }
  }

  ** A comp of a resolved graph
  Dict comp(Dict g, Str name) { g[name] as Dict ?: throw Err("no comp $name in " + Etc.dictNames(g).findAll { g[it] is Dict }) }

  ** The names of the comps of a resolved graph
  Str[] compNames(Dict g) { Etc.dictNames(g).findAll { g[it] is Dict }.sort }

  ** The endpoint a comp's slot is linked from, as "comp.slot", or null
  Str? linkOf(Dict g, Str name, Str slot)
  {
    links := comp(g, name)["links"] as Links
    if (links == null || !links.isLinked(slot)) return null
    l := links.listOn(slot).first
    from := Etc.dictNames(g).find |n| { (g[n] as Dict)?.get("id") == l.fromRef }
    return "${from}.${l.fromSlot}"
  }

  ** The value of a slot, or of the feed linked into it
  Obj? valOf(Dict g, Str name, Str slot)
  {
    v := comp(g, name)[slot]
    if (v != null) return v
    src := linkOf(g, name, slot)
    if (src == null) return null
    toks := src.split('.')
    return comp(g, toks[0])[toks[1]]
  }

  ** The number inside a Number or StatusNumber
  Number num(Obj? v)
  {
    if (v is StatusNumber) return ((StatusNumber)v).num
    return v as Number ?: throw Err("not a number: $v")
  }

  Void verifyNum(Obj? v, Float want, Str? unit)
  {
    n := num(v)
    verify((n.toFloat - want).abs < 1e-9f * want.abs.max(1f), "$n is not $want")
    verifyEq(n.unit?.symbol, unit)
  }

  ** Load a resolved graph into a comp space, keeping its ids
  CompSpace load(Dict g)
  {
    try CompSpace.uninstall; catch (Err e) {}
    cs := CompSpace(ns).install
    Actor.locals[ActorContext.actorLocalsKey] = TestCx(DateTime.fromIso("2026-10-31T12:00:00Z"))
    cs.loadXeto(CdlResolver.toXeto(ns, g)).start
    return cs
  }

  Void execute(CompSpace cs, Int n := 1)
  {
    cx := (TestCx)Actor.locals[ActorContext.actorLocalsKey]
    n.times { cx.now = cx.now + 1sec; cs.execute }
  }

  override Void teardown() { try CompSpace.uninstall; catch (Err e) {} }
}

internal class TestCx : CompContext
{
  new make(DateTime t) { now = t }
  override DateTime now
}
