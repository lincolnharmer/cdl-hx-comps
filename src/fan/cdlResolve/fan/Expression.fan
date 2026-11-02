//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

**
** CDL expressions as the libraries write them in `cdlBind`,
** `cdlCondition`, `cdlDefault`, `cdlArraySize`, `cdlEnable` and the bound
** meta.
**
** The source is first read into a small tree, then the tree is evaluated
** against an environment of CDL names. A value is a Float, a Bool, a Str
** (the item name of an enumeration) or a List (a vector, or a list of rows
** of equal length for a matrix).
**
** Forms, loosest first:
**   - `if c then a else b`, only where an expression starts: at the top, in
**     parentheses, as a call argument or literal element, and as a branch.
**     Only the branch the condition picks is evaluated. `elseif` refuses.
**   - `or`, `and`, which stop at the first operand that decides them;
**   - `not`;
**   - one comparison: `< <= > >=` on numbers, `== <>` on two scalars of one
**     kind (numbers, Booleans or enumeration items);
**   - the range `a:b` of whole numbers;
**   - `+ -`, then `* /`, then unary `- +`;
**   - numbers, `true`, `false`, names, dotted names (an enumeration item or
**     a package constant, which the caller resolves), `( )`, `{ }` lists,
**     `[ ; ]` matrices, `fill(v, n)`, `fill(v, n, m)`, `size(name, 1|2)`.
**
** Anything else refuses with the whole source quoted: a subscript, another
** function, a list where a scalar is needed, a value of the wrong kind.
**
const class Expression
{
  ** Evaluate `src` against `env`. `dotted` gives a dotted name's value, or
  ** null when the name is neither an enumeration item nor a constant.
  static Obj eval(Str text, Str:Obj? vars, |Str->Obj?| resolveDotted)
  {
    tree := ExprReader(text).read
    return ExprRun(text, vars, resolveDotted).run(tree)
  }

  ** Each name `src` mentions, dotted or not, once, in reading order
  static Str[] names(Str src)
  {
    acc := Str[,]
    ExprLexer.lex(src).each |tok|
    {
      if (tok.kind != ExprTok.word || ExprLexer.reserved.contains(tok.text) || acc.contains(tok.text)) return
      acc.add(tok.text)
    }
    return acc
  }

  ** The refusal for `src`
  internal static CdlResolveErr bad(Str src, Str why) { CdlResolveErr("cannot evaluate '$src': $why") }
}

**************************************************************************
** Lexer
**************************************************************************

internal enum class ExprTok { number, word, sym, end }

internal const class ExprToken
{
  new make(ExprTok kind, Str text, Float num := 0f) { this.kind = kind; this.text = text; this.num = num }
  const ExprTok kind
  const Str text
  const Float num
  Bool isSym(Str s) { kind == ExprTok.sym && text == s }
  Bool isWord(Str s) { kind == ExprTok.word && text == s }
  override Str toStr() { kind == ExprTok.end ? "end of expression" : "'$text'" }
}

internal const class ExprLexer
{
  static const Str[] reserved := ["true", "false", "not", "and", "or", "if", "then", "else", "elseif"]
  static const Str[] twoChar := ["<=", ">=", "==", "<>"]
  static const Str singles := "+-*/()<>,{}[];:"

  static ExprToken[] lex(Str src)
  {
    out := ExprToken[,]
    i := 0
    n := src.size
    while (i < n)
    {
      ch := src[i]
      if (ch.isSpace) { i++; continue }
      start := i
      if (ch.isDigit || (ch == '.' && i + 1 < n && src[i+1].isDigit))
      {
        while (i < n && src[i].isDigit) i++
        if (i < n && src[i] == '.') { i++; while (i < n && src[i].isDigit) i++ }
        if (i < n && (src[i] == 'e' || src[i] == 'E'))
        {
          j := i + 1
          if (j < n && (src[j] == '+' || src[j] == '-')) j++
          if (j < n && src[j].isDigit) { i = j; while (i < n && src[i].isDigit) i++ }
        }
        text := src[start..<i]
        out.add(ExprToken(ExprTok.number, text, Float.fromStr(text)))
        continue
      }
      if (ch.isAlpha || ch == '_')
      {
        // a word, with any dotted segments that follow
        while (true)
        {
          while (i < n && (src[i].isAlphaNum || src[i] == '_')) i++
          if (i + 1 < n && src[i] == '.' && (src[i+1].isAlpha || src[i+1] == '_')) { i++; continue }
          break
        }
        out.add(ExprToken(ExprTok.word, src[start..<i]))
        continue
      }
      if (i + 1 < n && twoChar.contains(src[i..i+1])) { out.add(ExprToken(ExprTok.sym, src[i..i+1])); i += 2; continue }
      if (singles.containsChar(ch)) { out.add(ExprToken(ExprTok.sym, ch.toChar)); i++; continue }
      throw Expression.bad(src, "the character '${ch.toChar}' is not part of the grammar")
    }
    out.add(ExprToken(ExprTok.end, ""))
    return out
  }
}

**************************************************************************
** Tree
**************************************************************************

internal abstract const class ExprNode {}

internal const class ExprLit : ExprNode
{
  new make(Obj v) { this.v = v }
  const Obj v
}

internal const class ExprRef : ExprNode
{
  new make(Str name) { this.name = name }
  const Str name
}

internal const class ExprOp : ExprNode
{
  new make(Str op, ExprNode[] args) { this.op = op; this.args = args }
  ** neg, pos, not, and, or, + - * /, < <= > >= == <>, range, if, fill,
  ** size, list, matrix
  const Str op
  const ExprNode[] args
}

**************************************************************************
** Reader
**************************************************************************

**
** Reads tokens into a tree. Binary operators climb by precedence; a
** comparison and a range take one operator each, as Modelica's grammar
** does.
**
internal class ExprReader
{
  new make(Str src) { this.src = src; this.toks = ExprLexer.lex(src) }

  const Str src
  ExprToken[] toks
  Int pos

  ExprToken cur() { toks[pos] }
  ExprToken next() { t := toks[pos]; if (t.kind != ExprTok.end) pos++; return t }
  Void expect(Str sym, Str why)
  {
    if (!cur.isSym(sym)) throw Expression.bad(src, "$why, found ${cur}")
    next
  }

  ExprNode read()
  {
    node := expr
    if (cur.kind != ExprTok.end) throw Expression.bad(src, "${cur} after a complete expression")
    return node
  }

  ** An expression where one may start: an if-expression or a disjunction
  ExprNode expr()
  {
    if (!cur.isWord("if")) return binary(0)
    next
    c := expr
    if (!cur.isWord("then")) throw Expression.bad(src, "an if needs then, found ${cur}")
    next
    a := expr
    if (cur.isWord("elseif")) throw Expression.bad(src, "elseif is not supported")
    if (!cur.isWord("else")) throw Expression.bad(src, "an if needs else, found ${cur}")
    next
    b := expr
    return ExprOp("if", [c, a, b])
  }

  ** Binary operator levels, loosest first
  static const Str[][] levels := [["or"], ["and"], ["not"], ["<", "<=", ">", ">=", "==", "<>"], [":"], ["+", "-"], ["*", "/"]]

  Bool atOp(Str[] ops)
  {
    t := cur
    if (t.kind == ExprTok.word) return ops.contains(t.text) && (t.text == "or" || t.text == "and")
    return t.kind == ExprTok.sym && ops.contains(t.text)
  }

  ExprNode binary(Int level)
  {
    if (level == levels.size) return unary
    ops := levels[level]
    if (ops.first == "not")
    {
      if (cur.isWord("not")) { next; return ExprOp("not", [binary(level)]) }
      return binary(level + 1)
    }
    left := binary(level + 1)
    single := level == 3 || level == 4
    while (atOp(ops))
    {
      op := next.text
      right := binary(level + 1)
      left = ExprOp(op == ":" ? "range" : op, [left, right])
      if (single)
      {
        if (atOp(ops)) throw Expression.bad(src, op == ":" ? "a range takes no step" : "comparisons do not chain")
        break
      }
    }
    return left
  }

  ExprNode unary()
  {
    if (cur.isSym("-")) { next; return ExprOp("neg", [unary]) }
    if (cur.isSym("+")) { next; return ExprOp("pos", [unary]) }
    node := primary
    if (cur.isSym("[")) throw Expression.bad(src, "subscripts are not supported")
    return node
  }

  ExprNode primary()
  {
    t := next
    switch (t.kind)
    {
      case ExprTok.number: return ExprLit(t.num)
      case ExprTok.end: throw Expression.bad(src, "it ends where a value is needed")
      case ExprTok.sym:
        if (t.text == "(") { e := expr; expect(")", "a ( needs its )"); return e }
        if (t.text == "{") return list
        if (t.text == "[") return matrix
        throw Expression.bad(src, "${t} where a value is needed")
    }
    w := t.text
    if (w == "true" || w == "false") return ExprLit(w == "true")
    if (ExprLexer.reserved.contains(w)) throw Expression.bad(src, "'$w' where a value is needed")
    if (cur.isSym("("))
    {
      if (w == "fill") return ExprOp("fill", callArgs)
      if (w == "size") return sizeCall
      throw Expression.bad(src, "the function $w is not supported")
    }
    return ExprRef(w)
  }

  ExprNode[] callArgs()
  {
    expect("(", "a call needs (")
    acc := ExprNode[,]
    acc.add(expr)
    while (cur.isSym(",")) { next; acc.add(expr) }
    expect(")", "a call needs its )")
    return acc
  }

  ExprNode sizeCall()
  {
    expect("(", "size needs (")
    t := next
    if (t.kind != ExprTok.word || t.text.contains(".") || ExprLexer.reserved.contains(t.text) || cur.isSym("("))
      throw Expression.bad(src, "size reads a parameter named directly")
    expect(",", "size takes a name and a dimension")
    d := expr
    expect(")", "size takes a name and a dimension")
    return ExprOp("size", [ExprRef(t.text), d])
  }

  ExprNode list()
  {
    acc := ExprNode[,]
    if (cur.isSym("}")) { next; return ExprOp("list", acc) }
    acc.add(expr)
    while (cur.isSym(",")) { next; acc.add(expr) }
    expect("}", "a { needs its }")
    return ExprOp("list", acc)
  }

  ExprNode matrix()
  {
    if (cur.isSym("]")) throw Expression.bad(src, "a matrix needs at least one element")
    rows := ExprNode[,]
    row := ExprNode[,]
    while (true)
    {
      row.add(expr)
      if (cur.isSym(",")) { next; continue }
      rows.add(ExprOp("list", row))
      row = ExprNode[,]
      if (cur.isSym(";")) { next; continue }
      expect("]", "a [ needs its ]")
      break
    }
    return ExprOp("matrix", rows)
  }
}

**************************************************************************
** Run
**************************************************************************

internal class ExprRun
{
  new make(Str text, Str:Obj? vars, |Str->Obj?| resolveDotted) { this.text = text; this.vars = vars; this.resolveDotted = resolveDotted }

  const Str text
  Str:Obj? vars
  |Str->Obj?| resolveDotted

  CdlResolveErr bad(Str why) { Expression.bad(text, why) }

  Float num(Obj? v, Str role)
  {
    if (v is Float) return v
    throw bad("$role must be a number, and is ${Values.show(v)}")
  }

  Bool flag(Obj? v, Str role)
  {
    if (v is Bool) return v
    throw bad("$role must be a Boolean, and is ${Values.show(v)}")
  }

  Int whole(Obj? v, Str role)
  {
    f := num(v, role)
    if (f < 0f || f != f.floor) throw bad("$role must be a whole number of at least 0, and is ${Values.show(f)}")
    return f.toInt
  }

  Obj run(ExprNode node)
  {
    if (node is ExprLit) return ((ExprLit)node).v
    if (node is ExprRef) return lookup(((ExprRef)node).name)
    op := (ExprOp)node
    a := op.args
    switch (op.op)
    {
      case "if":    return flag(run(a[0]), "an if condition") ? run(a[1]) : run(a[2])
      case "or":    return flag(run(a[0]), "an or operand") ? true : flag(run(a[1]), "an or operand")
      case "and":   return !flag(run(a[0]), "an and operand") ? false : flag(run(a[1]), "an and operand")
      case "not":   return !flag(run(a[0]), "a not operand")
      case "neg":   return -num(run(a[0]), "a negated value")
      case "pos":   return num(run(a[0]), "a signed value")
      case "+":     return num(run(a[0]), "a sum's operand") + num(run(a[1]), "a sum's operand")
      case "-":     return num(run(a[0]), "a difference's operand") - num(run(a[1]), "a difference's operand")
      case "*":     return num(run(a[0]), "a product's factor") * num(run(a[1]), "a product's factor")
      case "/":
        top := num(run(a[0]), "a quotient's dividend")
        bottom := num(run(a[1]), "a quotient's divisor")
        if (bottom == 0f) throw bad("it divides by zero")
        return top / bottom
      case "<":     return num(run(a[0]), "a compared value") < num(run(a[1]), "a compared value")
      case "<=":    return num(run(a[0]), "a compared value") <= num(run(a[1]), "a compared value")
      case ">":     return num(run(a[0]), "a compared value") > num(run(a[1]), "a compared value")
      case ">=":    return num(run(a[0]), "a compared value") >= num(run(a[1]), "a compared value")
      case "==":    return same(run(a[0]), run(a[1]))
      case "<>":    return !same(run(a[0]), run(a[1]))
      case "range":
        lo := num(run(a[0]), "a range bound"); hi := num(run(a[1]), "a range bound")
        if (lo != lo.floor || hi != hi.floor) throw bad("a range needs whole bounds, not ${Values.show(lo)}:${Values.show(hi)}")
        acc := Obj?[,]
        for (x := lo; x <= hi; x += 1f) acc.add(x)
        return acc
      case "list":  return listOf(a.map |x->Obj?| { run(x) })
      case "matrix":
        rows := a.map |x->Obj?| { run(x) }
        rows.each |List r| { if (r.any { it is List }) throw bad("a matrix element must be a scalar") }
        if (rows.map |List r->Int| { r.size }.unique.size > 1) throw bad("a matrix needs rows of one length")
        return rows
      case "fill":  return fill(a)
      case "size":  return size(((ExprRef)a[0]).name, run(a[1]))
    }
    throw bad("unknown operation ${op.op}")
  }

  ** A name's value, or a dotted name's through the caller
  Obj lookup(Str name)
  {
    if (name.contains("."))
    {
      v := resolveDotted(name)
      if (v == null) throw bad("$name is neither an enumeration item nor a package constant")
      return v
    }
    v := vars[name]
    if (v == null) throw bad("unknown name $name")
    return v
  }

  ** == and <> take two scalars of one kind
  Bool same(Obj? x, Obj? y)
  {
    if (x is List || y is List) throw bad("== and <> compare scalars, not arrays")
    if (x?.typeof != y?.typeof) throw bad("== and <> compare values of one kind, not ${Values.show(x)} and ${Values.show(y)}")
    return x == y
  }

  ** A literal list: scalars, or rows of scalars of one length
  Obj listOf(Obj?[] items)
  {
    rows := items.findAll { it is List }
    if (rows.isEmpty) return items
    if (rows.size != items.size) throw bad("a list mixes rows and scalars")
    rows.each |List r| { if (r.any { it is List }) throw bad("lists nest two deep at most") }
    if (rows.map |List r->Int| { r.size }.unique.size > 1) throw bad("a list needs rows of one length")
    return items
  }

  Obj fill(ExprNode[] a)
  {
    if (a.size < 2 || a.size > 3) throw bad("fill takes a value and one or two counts")
    v := run(a[0])
    if (v isnot Float && v isnot Bool) throw bad("fill repeats a number or a Boolean, not ${Values.show(v)}")
    n := whole(run(a[1]), "a fill count")
    if (a.size == 2)
    {
      acc := Obj?[,]
      n.times { acc.add(v) }
      return acc
    }
    m := whole(run(a[2]), "a fill count")
    rows := Obj?[,]
    n.times
    {
      r := Obj?[,]
      m.times { r.add(v) }
      rows.add(r)
    }
    return rows
  }

  Obj size(Str name, Obj? dim)
  {
    if (dim != 1f && dim != 2f) throw bad("size reads dimension 1 or 2, not ${Values.show(dim)}")
    arr := lookup(name) as List ?: throw bad("size reads an array, and $name is not one")
    if (dim == 1f) return arr.size.toFloat
    if (arr.isEmpty || arr.any { it isnot List }) throw bad("$name has one dimension, so size cannot read its second")
    return ((List)arr.first).size.toFloat
  }
}
