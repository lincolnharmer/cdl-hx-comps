//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//
// Replays one MBL G36 validation model through the cdlResolve flat hx.comps graph.
// Run: fan G36Replay.fan <scenario.json>...
//
// The scenario (gen_inputs.py) names the controller, its parameters from the validation model, the step, the end
// time and an input CSV computed from the validation model's source blocks. Each step: apply the CSV row for this
// time, setting a point input only when its value changes; set the closed-loop inputs from the feedback blocks;
// move the clock to start + t; execute the comp space once; read the point outputs; update the feedback blocks
// (the validation model's own Not, Timer and Latch, in MBL semantics, on this step's outputs, so a loop through
// the validation model carries one step of delay). Writes:
//   trace.csv    every recorded column on every step within `window` steps of a reference grid or raw time, and two
//                steps either side of every event (a change logged in changes.csv or events.csv)
//   events.csv   every change of every Boolean comp in the graph: the model's events, as Dymola stores events
//   graph.xeto, driver.txt  the resolved graph, and the harness revision (environment variable G36_HARNESS_REV)
//   changes.csv  every change of a Boolean or Integer (unit-less) point output and Boolean input, over all steps
// and prints the resolve summary, fault counts and the run time.
//
using concurrent
using util
using xeto
using haystack
using hxComps
using cdlResolve
using xetom

class ReplayCx : CompContext
{
  new make(DateTime t) { now = t }
  override DateTime now
}

** Trace-writing state of one run: rows go out around every event
class RowState
{
  Bool anyEvent := false
  Int lastWritten := -1
  Int forceUntil := -1
  Str? buf1
  Str? buf2
  Str:Comp boolComps := [:]
  Str:Bool lastBool := [:]
  OutStream? evo
  OutStream? trace
  OutStream? chg
  Str:Str lastLogged := [:]
  InStream? inp
  Str? pending

  ** Write this step's row when it is recorded or near an event; the two rows before an event go out with it
  Void write(Int k, Str row, Bool recorded)
  {
    if (anyEvent)
    {
      if (k - 2 > lastWritten && buf2 != null) trace.printLine(buf2)
      if (k - 1 > lastWritten && buf1 != null) trace.printLine(buf1)
      forceUntil = k + 2
    }
    if (recorded || anyEvent || k <= forceUntil) { trace.printLine(row); lastWritten = k }
    buf2 = buf1
    buf1 = row
    anyEvent = false
  }
}

** One feedback block of the validation model, in MBL semantics
class FbBlock
{
  Str name := ""
  Str type := ""
  Str:Obj? params := [:]
  Str:Str inputs := [:]
  // state
  Bool y := false
  Bool passed := false
  Float entry := 0f
  Bool prevU := false
  Bool prevClr := false
  Bool inited := false
  Float yReal := 0f

  Obj? out(Str port) { port == "passed" ? passed : (type == "Timer" && port == "y" ? yReal : y) }

  Void update(Float t, |Str->Obj?| read)
  {
    switch (type)
    {
      case "Not":
        y = !toB(read(inputs["u"]))
      case "Timer":
        u := toB(read(inputs["u"]))
        th := ((Num)params["t"]).toFloat
        if (!inited) { entry = t; passed = th <= 0f; inited = true }
        else if (u && !prevU) { entry = t; passed = th <= 0f }
        else if (u && t >= th + entry) passed = true
        else if (!u && prevU) passed = false
        yReal = u ? t - entry : 0f
        prevU = u
      case "Latch":
        u := toB(read(inputs["u"])); clr := toB(read(inputs["clr"]))
        if (!inited || (u && !prevU) || (clr && !prevClr)) y = !clr && u
        inited = true; prevU = u; prevClr = clr
      default: throw Err("feedback block type $type")
    }
  }

  static Bool toB(Obj? v)
  {
    if (v is Bool) return v
    if (v is StatusBool) return ((StatusBool)v).val
    if (v is Num) return ((Num)v).toFloat > 0.5f
    if (v is StatusNumber) return ((StatusNumber)v).num.toFloat > 0.5f
    throw Err("not a boolean: $v")
  }
}

class G36Replay
{
  ** Args: one or more scenario files. Several scenarios run one after another in this JVM, each in a fresh comp
  ** space.
  Int main(Str[] args)
  {
    rc := 0
    args.each |f|
    {
      try { r := runOne(f); if (r != 0) rc = r }
      catch (Err e) { echo("RUN ERR $f: $e"); e.trace; rc = 4 }
    }
    return rc
  }

  Int runOne(Str file)
  {
    sc := (Str:Obj?)JsonInStream(File.os(file).in).readJson
    ns := XetoEnv.cur.resolveNamespace(["kw.cdl.g36.terminal", "kw.cdl.g36.ahu"])
    qn := sc["qname"].toStr
    params := Str:Obj[:]
    ((Str:Obj?)sc["params"]).each |v, k| { if (v != null) params[k] = toParam(v) }
    echo("== $qn  model " + sc["model"] + " " + sc["instance"] + "  step " + sc["step"] + " s  tEnd " + sc["tEnd"] + " s")
    echo("params: $params")
    t0 := Duration.now
    Dict? g := null
    try g = CdlResolver(ns).resolve(qn, Etc.makeDict(params))
    catch (CdlResolveErr e) { echo("REFUSED: $e.msg"); return 3 }
    x := CdlResolver.toXeto(ns, g)
    try CompSpace.uninstall; catch (Err e) {}
    cs := CompSpace(ns).install
    start := DateTime.fromIso(sc["startIso"].toStr)
    cx := ReplayCx(start)
    Actor.locals[ActorContext.actorLocalsKey] = cx
    cs.loadXeto(x).start
    rd := File.os(sc["trace"].toStr).parent
    provenance(rd, x, file, sc)

    Str:Comp ins := [:] { ordered = true }
    Str:Comp outs := [:] { ordered = true }
    Str:Unit? inUnit := [:]
    Str:Bool outInt := [:]
    ncomps := 0
    cs.root.each |v, nm|
    {
      c := v as Comp
      if (c == null) return
      ncomps++
      // an array connector's elements share cdlName; their cdlPath carries the index (uOpeMod[1])
      cp := c.get("cdlPath")?.toStr
      cdl := (cp != null && cp.contains("[")) ? cp : (c.get("cdlName")?.toStr ?: nm)
      if (c.spec.name.endsWith("PointInput"))
      {
        ins[cdl] = c
        u := c.get("cdlUnit")?.toStr
        inUnit[cdl] = (u == null || u == "1") ? null : Unit.fromStr(u, false)
      }
      else if (c.spec.name.endsWith("PointOutput"))
      {
        outs[cdl] = c
        outInt[cdl] = c.spec.name.startsWith("Bool") || c.get("cdlUnit") == null
      }
    }
    echo("resolved in ${(Duration.now - t0).toMillis} ms: $ncomps comps, ${ins.size} inputs ${ins.keys}, ${outs.size} outputs ${outs.keys}")

    // inputs CSV
    rs := RowState()
    // the inputs CSV is streamed, a row at a time
    rs.inp = File.os(sc["inputsCsv"].toStr).in
    hdr := rs.inp.readLine.split(',')
    rs.pending = rs.inp.readLine
    Str:Obj? curIn := [:]
    // an input the graph does not take, or a point input nothing drives, invalidates the run
    errs := Str[,]
    hdr.each |h, i| { if (i > 0 && !h.startsWith("src:") && ins[h] == null) errs.add("input column $h has no point input") }
    ins.each |c, n| { if (!hdr.contains(n) && !((Str:Obj?)sc["feedbackInputs"]).containsKey(n)) errs.add("point input $n is driven by nothing") }
    if (!errs.isEmpty) { errs.each { echo("ERROR $it") }; rs.inp.close; return 5 }

    // feedback blocks
    fbs := Str:FbBlock[:] { ordered = true }
    ((List)sc["feedback"]).each |Str:Obj? d|
    {
      // it.: a bare `params` here would assign the method's own params local
      b := FbBlock { it.name = d["name"]; it.type = d["type"]; it.params = d["params"]; it.inputs = d["inputs"] }
      fbs[b.name] = b
    }
    fbIn := (Str:Obj?)sc["feedbackInputs"]
    fbInit := (Str:Obj?)sc["feedbackInit"]
    Str:Obj? fbVal := [:]
    // a closed-loop input starts from MBL's own initial value where the reference records it, else false or 0
    fbIn.each |src, n| { iv := fbInit[n]; fbVal[n] = iv == null ? 0f : ((Num)iv).toFloat }

    h := ((Num)sc["step"]).toFloat
    tEnd := ((Num)sc["tEnd"]).toFloat
    tStart := sc["tStart"] == null ? 0f : ((Num)sc["tStart"]).toFloat
    nSteps := ((tEnd - tStart) / h).round.toInt
    hns := (h * 1e9f).round.toInt
    win := ((Num)sc["window"]).toInt
    rec := Int:Bool[:]
    // record a window around every reference grid time and around every raw Dymola output point a grid value is
    // interpolated from
    times := ((List)sc["grid"]).dup.addAll((List?)sc["extraTimes"] ?: [,])
    times.each |Num gt| { k := ((gt.toFloat - tStart) / h).round.toInt; (k - win..k + win).each |j| { if (j >= 0 && j <= nSteps) rec[j] = true } }
    cols := ((List)sc["record"]).map |Obj c->Str| { c.toStr }

    // a recorded column with a dot names an internal CDL signal: <instance path>.<port>; it reads the `out` of the
    // flat comp whose cdlPath is the instance path, or the flat comp at the cdlPath the scenario's `alias` gives (alias.py)
    byPath := Str:Comp[:]
    cs.root.each |v, nm| { c := v as Comp; p := c?.get("cdlPath")?.toStr; if (p != null) byPath[p] = c }
    alias := Str:Obj?[:]
    if (sc["alias"] != null) alias = sc["alias"]
    innerCols := Str:Comp[:]
    cols.each |Str col|
    {
      if (!col.contains(".")) return
      a := alias[col]
      c := byPath[a != null ? a.toStr : col[0..<col.indexr(".")]]
      if (c == null) { echo("WARN internal column " + col + ": no comp") }
      else { innerCols[col] = c }
    }
    // every Boolean comp in the graph: its changes are the model's events (events.csv), as Dymola stores events
    cs.root.each |v, nm| { c := v as Comp; if (c != null && !c.spec.name.contains("Point") && c.spec.slot("out", false)?.type?.name == "StatusBool") rs.boolComps[nm] = c }
    rs.evo = (rd + `events.csv`).out
    rs.evo.printLine("t,comp,val")
    rs.trace = File.os(sc["trace"].toStr).out
    rs.trace.printLine("t," + cols.join(","))
    rs.chg = File.os(sc["changes"].toStr).out
    rs.chg.printLine("t,col,val")

    faultSteps := Str:Int[:]
    nullSteps := Str:Int[:]
    tRun := Duration.now
    (0..nSteps).each |k|
    {
      t := tStart + k * h
      // open-loop inputs
      while (rs.pending != null)
      {
        r := rs.pending.split(',')
        rt := r[0].toFloat
        if (rt > t + h * 1e-6f) break
        hdr.each |col, i| { if (i > 0) curIn[col] = r[i].toFloat }
        rs.pending = rs.inp.readLine
      }
      hdr.each |col, i| { if (i > 0 && ins[col] != null) setIn(ins[col], col, curIn[col], inUnit[col]) }
      fbVal.each |v, n| { if (v != null) setIn(ins[n], n, v, inUnit[n]) }
      cx.now = start + Duration((tStart * 1e9f).round.toInt + k * hns)
      cs.execute
      // outputs
      outs.each |c, n|
      {
        v := c.get("in")
        if (v == null) { nullSteps[n] = (nullSteps[n] ?: 0) + 1; return }
        if ((v as StatusVal)?.status?.isOk == false) faultSteps[n] = (faultSteps[n] ?: 0) + 1
        if (outInt[n])
        {
          s := fmt(v)
          if (rs.lastLogged[n] != s) { if (rs.lastLogged.containsKey(n)) rs.anyEvent = true; rs.chg.printLine("${fmtT(t)},$n,$s"); rs.lastLogged[n] = s }
        }
      }
      ins.each |c, n|
      {
        if (!c.spec.name.startsWith("Bool") && c.get("cdlUnit") != null) return
        s := fmt(c.get("curVal"))
        if (rs.lastLogged["in:"+n] != s) { rs.chg.printLine("${fmtT(t)},in:$n,$s"); rs.lastLogged["in:"+n] = s; rs.anyEvent = true }
      }
      if (logBools(rs.boolComps, rs.lastBool, rs.evo, t)) rs.anyEvent = true
      row := fmtT(t) + "," + cols.map |col->Str| { ic := innerCols[col]; return ic != null ? fmt(ic.get("out")) : fmt(outs[col]?.get("in") ?: ins[col]?.get("curVal")) }.join(",")
      // rows go out around every grid and raw point, and two steps either side of every event
      rs.write(k, row, rec[k] == true)
      // feedback blocks see this step's outputs; their outputs feed the next step
      if (!fbs.isEmpty || !fbIn.isEmpty)
      {
        read := |Str ref->Obj?|
        {
          if (ref.startsWith("out:")) return outs[ref[4..-1]].get("in")
          if (ref.startsWith("blk:")) { p := ref[4..-1].split('.'); return fbs[p[0]].out(p[1]) }
          if (ref.startsWith("in:")) return curIn[ref[3..-1]]
          throw Err(ref)
        }
        fbs.each |b| { b.update(t, read) }
        fbIn.each |src, n|
        {
          v := read(src)
          nv := v is Bool ? (((Bool)v) ? 1f : 0f) : (v is Float ? v : (v is StatusBool ? (((StatusBool)v).val ? 1f : 0f) : ((StatusNumber)v).num.toFloat))
          if (nv != fbVal[n]) echo("feedback $n = $nv at t=$t for the next step (" + fbs.vals.map |b->Str| { b.name + ":" + b.y + "/" + b.passed } .join(" ") + ")")
          fbVal[n] = nv
        }
      }
    }
    rs.trace.close
    rs.chg.close
    rs.evo.close
    rs.inp.close
    secs := (Duration.now - tRun).toMillis / 1000f
    echo("ran ${nSteps + 1} steps in ${secs} s")
    echo("non-ok output steps: $faultSteps")
    echo("null output steps: $nullSteps")
    // comps whose out is faulted at the end
    nf := 0
    cs.root.each |v, nm|
    {
      c := v as Comp
      if (c == null || c.spec.slot("out", false) == null) return
      st := (c.get("out") as StatusVal)?.status
      if (st != null && !st.isOk) { nf++; if (nf <= 40) echo("  end status $nm [${c.spec.name}] = " + c.get("out")) }
    }
    echo("comps with a non-ok out at the end: $nf")
    return 0
  }

  ** Log every Boolean comp whose out changed this step; true if any did
  static Bool logBools(Str:Comp boolComps, Str:Bool lastBool, OutStream evo, Float t)
  {
    any := false
    boolComps.each |c, nm|
    {
      b := (c.get("out") as StatusBool)?.val
      if (b == null || lastBool[nm] == b) return
      if (lastBool.containsKey(nm)) { evo.printLine(fmtT(t) + "," + nm + "," + (b ? "1" : "0")); any = true }
      lastBool[nm] = b
    }
    return any
  }

  ** graph.xeto and driver.txt (the harness revision run.sh passes) next to the trace
  static Void provenance(File rd, Str x, Str file, Str:Obj? sc)
  {
    (rd + `graph.xeto`).out.print(x).close
    out := (rd + `driver.txt`).out
    out.printLine("harnessRev=" + (Env.cur.vars["G36_HARNESS_REV"] ?: "unknown"))
    out.printLine("scenario=" + file)
    out.printLine("step=" + sc["step"])
    out.printLine("started=" + DateTime.now.toIso)
    out.close
  }

  static Obj toParam(Obj v)
  {
    if (v is Num) return Number(((Num)v).toFloat)
    if (v is List) return ((List)v).map |x->Obj| { toParam(x) }
    return v
  }

  static Void setIn(Comp c, Str name, Obj? v, Unit? u)
  {
    if (v == null) return
    f := ((Num)v).toFloat
    if (c.spec.name.startsWith("Bool"))
    {
      b := f > 0.5f
      cur := c.get("curVal") as StatusBool
      if (cur != null && cur.val == b) return
      c.set("curVal", StatusBool(b, Status.ok))
    }
    else
    {
      cur := c.get("curVal") as StatusNumber
      if (cur != null && cur.num.toFloat == f) return
      c.set("curVal", StatusNumber(Number(f, u), Status.ok))
    }
  }

  static Str fmtT(Float t) { t == t.floor ? t.toInt.toStr : t.toStr }

  static Str fmt(Obj? v)
  {
    if (v == null) return "null"
    if (v is StatusBool)
    {
      b := (StatusBool)v
      return (b.val ? "1" : "0") + (b.status.isOk ? "" : ":" + b.status)
    }
    if (v is StatusNumber)
    {
      x := (StatusNumber)v
      return x.num.toFloat.toStr + (x.status.isOk ? "" : ":" + x.status)
    }
    if (v is Bool) return ((Bool)v) ? "1" : "0"
    if (v is Number) return ((Number)v).toFloat.toStr
    return "?" + v.typeof.name
  }
}
