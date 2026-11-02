//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack

**
** The Axon function wrapper: the kw.cdl.resolve lib declares it and binds
** it to this pod
**
class FuncTest : Test
{
  ** Wrong behaviour caught: the function declared in the lib with no Fantom
  ** binding, so calling it from Axon fails, or bound to a different method.
  Void testAxonFuncBinds()
  {
    ns := XetoEnv.cur.resolveNamespace(["kw.cdl.resolve", "kw.cdl"])
    f := ns.lib("kw.cdl.resolve").funcs.get("cdlResolve")
    verifyEq(f.func.params.map |p->Str| { p.name }, ["qname", "params", "opts"])
    // the thunk binds lazily: reading it raises when no Fantom method backs it
    verifyNotNull(f.func.thunk)
    verify(f.func.hasThunk, "no Fantom binding for kw.cdl.resolve::cdlResolve")
    m := KwCdlResolveFuncs#cdlResolve
    verify(m.hasFacet(Type.find("axon::Axon")), "cdlResolve has no @Axon facet")
    verifyEq(m.params.map |p->Str| { p.name }, ["qname", "params", "opts"])
  }
}
