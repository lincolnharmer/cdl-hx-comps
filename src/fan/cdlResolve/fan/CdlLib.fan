//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack

**
** What the resolver reads from the namespace: the CdlClass instances,
** the CDL enumerations and the package constants, indexed once.
**
internal class CdlLib
{
  new make(Namespace ns)
  {
    this.ns = ns
    ns.libs.each |lib|
    {
      if (!lib.name.startsWith("kw.cdl")) return
      lib.specs.each |s|
      {
        path := s.meta["cdlClass"] as Str
        if (path != null && s.isEnum) enums[path] = s
      }
      lib.instances.each |d|
      {
        spec := d["spec"]?.toStr
        if (spec == "kw.cdl::CdlConstants") constPkgs[d["cdlClass"].toStr] = d
      }
    }
  }

  Namespace ns

  ** The CdlClass instance a child names with `cdlOf`, or null
  Dict? classOf(Spec slot)
  {
    ref := slot.meta["cdlOf"] as Ref
    if (ref == null) return null
    c := classes[ref.id]
    if (c != null) return c
    c = ns.instance(ref.id, false) ?: throw CdlResolveErr("child ${slot.name}: cdlOf names $ref.id, which is not in the namespace")
    classes[ref.id] = c
    return c
  }

  ** The CdlClass of the CDL Line block, whose slot names a compound gain uses
  once Dict lineClass() { ns.instance("kw.cdl::cdl-RealsLine") }

  ** A dotted name's value: an enumeration item's key, or a package
  ** constant's value as a Float or Bool; null when it names neither
  Obj? dotted(Str name)
  {
    dot := name.indexr(".")
    if (dot == null) return null
    path := name[0..<dot]
    item := name[dot+1..-1]
    e := enums[path]
    if (e != null)
    {
      key := enumKeys(e).find { it == item }
      if (key != null) return key
    }
    pkg := constPkgs[path]
    if (pkg != null)
    {
      v := (pkg["cdlConstants"] as Dict)?.get(item)
      if (v != null) return Values.toEnv(v)
    }
    return null
  }

  ** The keys of an enumeration, as CDL spells them
  Str[] enumKeys(Spec e)
  {
    acc := Str[,]
    e.slots.each |s| { acc.add(s.meta["key"]?.toStr ?: s.name) }
    return acc
  }

  ** A function that resolves dotted names for Expression
  |Str->Obj?| dottedFunc() { |Str n->Obj?| { dotted(n) } }

  private Str:Dict classes := [:]
  private Str:Spec enums := [:]
  private Str:Dict constPkgs := [:]
}

**
** Conversions between Xeto values and the evaluator's values
**
internal const class Values
{
  ** A Xeto meta or slot value as an evaluator value: Float, Bool, Str or List
  static Obj? toEnv(Obj? v)
  {
    switch (v?.typeof?.toNonNullable)
    {
      case null:       return null
      case Float#:     return v
      case Bool#:      return v
      case Str#:       return v
      case Int#:       return ((Int)v).toFloat
      case Number#:    return ((Number)v).toFloat
    }
    list := v as List
    if (list != null) return list.map |x->Obj?| { toEnv(x) }
    // an enum item or another scalar reads as its key
    return v.toStr
  }

  ** The shape of an evaluator value: [] scalar, [n], or [n, m]
  static Int[] shapeOf(Obj? v)
  {
    list := v as List
    if (list == null) return Int[,]
    if (!list.any { it is List }) return [list.size]
    return [list.size, ((List)list.first).size]
  }

  ** Every scalar of a value, whatever its dimension
  static Obj?[] flat(Obj? v)
  {
    list := v as List
    if (list == null) return [v]
    acc := Obj?[,]
    list.each |x| { acc.addAll(flat(x)) }
    return acc
  }

  ** A value for a message
  static Str show(Obj? v)
  {
    if (v is Float)
    {
      f := (Float)v
      return f == f.floor && f.abs < 1e15f ? f.toInt.toStr : f.toStr
    }
    if (v is List) return "{" + ((List)v).join(", ") |x| { show(x) } + "}"
    return v?.toStr ?: "null"
  }
}
