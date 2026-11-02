//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack

**
** What one CDL instance resolved to
**
internal enum class InstKind
{
  composite,   // a G36 composite or a composed kw.cdl class: holds children
  comp,        // an elementary class run by one hx.comps comp
  array,       // an array class, expanded when its outputs are read
  wire,        // a link class (IntegerToReal, Pre): data, never a comp
  feed         // a comp the generator added beside a child
}

**
** One resolved instance of the tree
**
internal class Inst
{
  new make(InstKind kind, Str path, Str cdlPath, Spec slot, Spec type, Inst? parent)
  {
    this.kind = kind
    this.path = path
    this.cdlPath = cdlPath
    this.slot = slot
    this.type = type
    this.parent = parent
  }

  const InstKind kind
  ** The instance path in Xeto slot names: `conLoo.conCoo`, `booToInt[2]`
  const Str path
  ** The instance path in CDL names
  const Str cdlPath
  ** The child slot in the parent's spec (the type itself for the root)
  Spec slot
  ** The type: a composite spec, an hx.comps comp, an array class
  Spec type
  Inst? parent
  ** The element index of a vectorized child, from 1
  Int? index
  ** A composite's or array's parameters (CDL names), or an elementary
  ** child's bound parameter values (CdlClass keys)
  Str:Obj? env := [:]
  ** The CdlClass of an elementary, array or wire child
  Dict? cls
  ** A composite's present children by name (`booToInt[2]` for elements)
  Str:Inst kids := [:]
  ** A composite's vectorized children: base name to element count
  Str:Int vec := [:]
  ** A composite's children and connectors that a condition removed
  Str:Bool gone := [:]
  ** The temperature kind of parameters: true for a difference, false for
  ** an absolute temperature, keyed as `env` is
  Str:Bool deltaFacts := [:]
  ** The SI unit of parameters, declared or passed on by a binding, keyed as
  ** `env` is
  Str:Str unitFacts := [:]
  ** The parameter each unit fact was declared on, keyed as `unitFacts`
  Str:Str unitFrom := [:]
  ** A composite's parameters left out because their enable condition is
  ** false, to the condition
  Str:Str exempt := [:]
  ** True for the root
  Bool isRoot() { parent == null }
  ** The flat comp name: dots and brackets become underscores
  Str flatName() { FlatGraph.flatName(path) }

  override Str toStr() { "$kind $path" }
}

**
** A scalar endpoint of the flat graph: one slot of one flat comp
**
internal const class Ep
{
  new make(Str comp, Str slot) { this.comp = comp; this.slot = slot }
  const Str comp
  const Str slot
  override Str toStr() { "${comp}.${slot}" }
  override Bool equals(Obj? that) { x := that as Ep; return x != null && x.comp == comp && x.slot == slot }
  override Int hash() { toStr.hash }
}

**
** A resolved driver: one endpoint for a scalar, or the elements of an
** array in row-major order with its shape. `cut` is true when a link on
** the way carries `loopCut`; `seed` is the starting value a Logical.Pre
** on the way gives its target.
**
internal class Sig
{
  new make(Ep[] eps, Int[] shape) { this.eps = eps; this.shape = shape }
  Ep[] eps
  Int[] shape
  Bool cut
  Obj? seed
  ** The SI unit and temperature kind facts of the connectors on the way
  Str[] units := [,]
  Bool[] deltas := [,]

  Bool isScalar() { shape.isEmpty }

  ** True when two shapes are equal, whatever the element type of the lists
  static Bool same(Int[] a, Int[] b)
  {
    if (a.size != b.size) return false
    for (i := 0; i < a.size; ++i) if (a[i] != b[i]) return false
    return true
  }

  ** Element k (from 1) of a one-dimensional signal, or row k of a
  ** two-dimensional one
  Sig elem(Int k)
  {
    if (shape.isEmpty) throw Err("elem of a scalar")
    if (shape.size == 1) return copyFacts(Sig([eps[k-1]], Int[,]))
    m := shape[1]
    return copyFacts(Sig(eps[(k-1)*m..<k*m], [m]))
  }

  Sig copyFacts(Sig to)
  {
    to.cut = cut; to.seed = seed; to.units = units.dup; to.deltas = deltas.dup
    return to
  }

  override Str toStr() { shape.isEmpty ? eps.first.toStr : "$shape $eps" }
}
