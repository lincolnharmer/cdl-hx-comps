//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using util

**
** The expression grammar. The cases of `res/expression-cases.json` are the
** one table the libraries' generator is held to too (a copy of the
** generator's own case table).
** The array and enable cases below are the further cases its test file
** runs.
**
class ExpressionTest : Test
{
  Str:Obj? table() { JsonInStream(typeof.pod.file(`/test/res/expression-cases.json`).in).readJson }

  ** JSON numbers as the evaluator holds them
  static Obj? norm(Obj? v)
  {
    if (v is Int) return ((Int)v).toFloat
    if (v is List) return ((List)v).map |x->Obj?| { norm(x) }
    return v
  }

  static Str:Obj? envOf(Obj? json)
  {
    acc := Str:Obj?[:]
    (json as Map)?.each |v, k| { acc[k] = norm(v) }
    return acc
  }

  Obj ev(Str src, Str:Obj? env := [:], Str prefix := "Buildings.Controls.OBC.ASHRAE.G36.Types.")
  {
    Expression.eval(src, env) |n|
    {
      if (n == "Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.occupied") return 1f
      if (n.startsWith(prefix)) return n[n.indexr(".")+1..-1]
      return null
    }
  }

  Void verifyRefuses(Str src, Str:Obj? env := [:])
  {
    try { r := ev(src, env); fail("accepted '$src' as ${Values.show(r)}") }
    catch (CdlResolveErr e) { verify(e.msg.contains(src), "refusal does not quote '$src': $e.msg") }
  }

  ** Wrong behaviour caught: the evaluator drifting from the shared table:
  ** any accepted case with another value or type, any refused case
  ** accepted, or a refusal that does not quote the source.
  Void testSharedTable()
  {
    t := table
    prefix := t["enumPrefix"].toStr
    accept := t["accept"] as List
    refuse := t["refuse"] as List
    verify(accept.size >= 19 && refuse.size >= 7)
    accept.each |Map c|
    {
      want := norm(c["want"])
      got := ev(c["src"], envOf(c["env"]), prefix)
      verifyEq(got, want, c["src"])
      verifyEq(got.typeof.toNonNullable, want.typeof.toNonNullable, c["src"])
    }
    refuse.each |Map c| { verifyRefuses(c["src"], envOf(c["env"])) }
  }

  ** Wrong behaviour caught: an or or and evaluating its second operand
  ** after the first decides it, or an if evaluating the branch it does not
  ** take, so an unknown name there refuses.
  Void testShortCircuit()
  {
    verifyEq(ev("true or nope"), true)
    verifyEq(ev("false and nope"), false)
    verifyEq(ev("if a then 1 else nope", ["a": true]), 1f)
    verifyRefuses("false or nope")
  }

  ** Wrong behaviour caught: a number compared with an enumeration item or a
  ** Boolean giving false rather than a refusal.
  Void testMixedComparisonRefuses()
  {
    verifyRefuses("u == Buildings.Controls.OBC.ASHRAE.G36.Types.HeatingCoil.None", ["u": 1f])
    verifyRefuses("a == 1", ["a": true])
    verifyEq(ev("u == Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes.occupied", ["u": 1f]), true)
  }

  ** Wrong behaviour caught: precedence or associativity off in arithmetic,
  ** a chained comparison accepted, or a division by zero giving infinity.
  Void testArithmetic()
  {
    verifyEq(ev("2 - 3 - 4"), -5f)
    verifyEq(ev("8 / 4 / 2"), 1f)
    verifyEq(ev("-2 * 3 + 1"), -5f)
    verifyEq(ev(".5 * 4"), 2f)
    verifyRefuses("1 < 2 < 3")
    verifyRefuses("a / (b - b)", ["a": 1f, "b": 2f])
  }

  ** Wrong behaviour caught: a dropped not, a lost parenthesis or a swapped
  ** operand in a rendered enable gate
  ** (test_a_dialog_enable_renders_to_the_text_both_evaluators_parse).
  Void testEnableGate()
  {
    text := "eneStd == Buildings.Controls.OBC.ASHRAE.G36.Types.EnergyStandard.ASHRAE90_1 and not (a or b) or have_frePro"
    env := Str:Obj?["eneStd": "ASHRAE90_1", "a": false, "b": false, "have_frePro": false]
    verifyEq(ev(text, env), true)
    env["a"] = true
    verifyEq(ev(text, env), false)
  }

  ** Wrong behaviour caught: fill or size refused, fill returning a scalar
  ** or the wrong count, size returning anything but the length as a Float
  ** (test_fill_and_size_evaluate).
  Void testFillAndSize()
  {
    verifyEq(ev("fill(1, nin)", ["nin": 3f]), Obj?[1f, 1f, 1f])
    verifyEq(ev("fill(2,nZon)", ["nZon": 2f]), Obj?[2f, 2f])
    verifyEq(ev("fill(true, 2)"), Obj?[true, true])
    verifyEq(ev("fill(1.5, 0)"), Obj?[,])
    verifyEq(ev("fill(a + 1, n * 2)", ["a": 1f, "n": 1f]), Obj?[2f, 2f])
    verifyEq(ev("size(k, 1)", ["k": Obj?[1f, 2f, 3f]]), 3f)
    verifyEq(ev("size(k,1) + 1", ["k": Obj?[1f]]), 2f)
    verifyEq(ev("gai", ["gai": Obj?[1f, 2f]]), Obj?[1f, 2f])
  }

  ** Wrong behaviour caught: a malformed fill or size, another function, a
  ** list where a scalar is needed, a subscript or a literal nested past two
  ** dimensions accepted (test_fill_and_size_refuse_what_they_must).
  Void testFillAndSizeRefuse()
  {
    verifyRefuses("fill(1, 2.5)")
    verifyRefuses("fill(1, -1)")
    verifyRefuses("fill(k, 2)", ["k": Obj?[1f]])
    verifyRefuses("fill(1)")
    verifyRefuses("fill(1, true)")
    verifyRefuses("size(k)", ["k": Obj?[1f]])
    verifyRefuses("size(k, 2)", ["k": Obj?[1f]])
    verifyRefuses("size(n, 1)", ["n": 2f])
    verifyRefuses("size(fill(1, 2), 1)")
    verifyRefuses("max(a, b)", ["a": 1f, "b": 2f])
    verifyRefuses("k + 1", ["k": Obj?[1f]])
    verifyRefuses("-k", ["k": Obj?[1f]])
    verifyRefuses("k > 1", ["k": Obj?[1f]])
    verifyRefuses("k == k", ["k": Obj?[1f]])
    verifyRefuses("not k", ["k": Obj?[true]])
    verifyRefuses("k and true", ["k": Obj?[true]])
    verifyRefuses("k[1]", ["k": Obj?[1f]])
    verifyRefuses("{{{1}}}")
  }

  ** Wrong behaviour caught: a brace literal, matrix literal, range,
  ** three-argument fill or size(a, 2) refused or given the wrong shape or
  ** order (test_two_dimensional_forms_evaluate).
  Void testTwoDimensionalForms()
  {
    verifyEq(ev("{2,3,1,4}"), Obj?[2f, 3f, 1f, 4f])
    verifyEq(ev("{{1,0},{1,0},{0,1},{0,1}}"), Obj?[Obj?[1f, 0f], Obj?[1f, 0f], Obj?[0f, 1f], Obj?[0f, 1f]])
    verifyEq(ev("{ true, false }"), Obj?[true, false])
    verifyEq(ev("{}"), Obj?[,])
    verifyEq(ev("{n, n + 1}", ["n": 2f]), Obj?[2f, 3f])
    verifyEq(ev("[1,0;0,1]"), Obj?[Obj?[1f, 0f], Obj?[0f, 1f]])
    verifyEq(ev("[1, 2]"), Obj?[Obj?[1f, 2f]])
    verifyEq(ev("1:nout", ["nout": 3f]), Obj?[1f, 2f, 3f])
    verifyEq(ev("2:n+1", ["n": 3f]), Obj?[2f, 3f, 4f])
    verifyEq(ev("3:2"), Obj?[,])
    verifyEq(ev("fill(0.5, 2, 3)"), Obj?[Obj?[0.5f, 0.5f, 0.5f], Obj?[0.5f, 0.5f, 0.5f]])
    verifyEq(ev("fill(true, 1, 2)"), Obj?[Obj?[true, true]])
    verifyEq(ev("size(K, 2)", ["K": Obj?[Obj?[1f, 0f, 1f], Obj?[0f, 1f, 0f]]]), 3f)
    verifyEq(ev("size(K, 1)", ["K": Obj?[Obj?[1f, 0f, 1f], Obj?[0f, 1f, 0f]]]), 2f)
    verifyEq(ev("size(K, 1) * size(K, 2)", ["K": Obj?[Obj?[1f], Obj?[2f]]]), 2f)
  }

  ** Wrong behaviour caught: a ragged, over-deep or mixed literal, a stepped
  ** or fractional range, a size past the second dimension, a subscript or a
  ** list in arithmetic accepted (test_two_dimensional_forms_refuse_what_they_must).
  Void testTwoDimensionalRefuse()
  {
    verifyRefuses("{{1},{2,3}}")
    verifyRefuses("{1,{2}}")
    verifyRefuses("[1,2;3]")
    verifyRefuses("[]")
    verifyRefuses("[k]", ["k": Obj?[1f]])
    verifyRefuses("1:2:3")
    verifyRefuses("1.5:3")
    verifyRefuses("size(m, 3)", ["m": Obj?[Obj?[1f]]])
    verifyRefuses("m[1,2]", ["m": Obj?[Obj?[1f, 2f]]])
    verifyRefuses("{1,2} + 1")
    verifyRefuses("m == m", ["m": Obj?[Obj?[1f]]])
  }

  ** Wrong behaviour caught: names() missing a dotted name or listing a
  ** keyword, which would make the parameter dependency order wrong.
  Void testNames()
  {
    verifyEq(Expression.names("not a and b.c or true or a + d"), ["a", "b.c", "d"])
    verifyEq(Expression.names("if x then y else z"), ["x", "y", "z"])
  }

  ** Wrong behaviour caught (R21): elseif refused for want of an else,
  ** which hides that the form itself is unsupported.
  Void testElseifRefusedByName()
  {
    try { ev("if a then 1 elseif b then 2 else 3", ["a": false, "b": true]); fail }
    catch (CdlResolveErr e) { verify(e.msg.contains("elseif is not supported"), e.msg) }
  }
}
