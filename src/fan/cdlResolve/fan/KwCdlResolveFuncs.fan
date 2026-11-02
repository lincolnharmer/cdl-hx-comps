//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack
using axon
using hx

**
** Axon functions of the kw.cdl.resolve lib
**
const class KwCdlResolveFuncs
{
  **
  ** Resolve one configured CDL composite into a flat hx.comps comp graph,
  ** returned as `sys.comp` data. `qname` names the composite, such as
  ** `kw.cdl.g36.terminal::TerminalUnitsCoolingOnlyController`, and `params`
  ** gives its parameter values by CDL name, with units. `opts` may give
  ** `pointUnits` (connector CDL name to unit) and `id` (the root id).
  ** Refuses, naming what it refused, rather than guess.
  **
  ** Example:
  **   cdlResolve("kw.cdl.g36.common::GenericTimeSuppression", {})
  **
  @Api @Axon static Dict cdlResolve(Str qname, Dict params, Dict? opts := null)
  {
    CdlResolver(Context.cur.ns).resolve(qname, params, opts)
  }
}
