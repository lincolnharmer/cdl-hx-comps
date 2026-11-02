//
// Copyright (c) 2026, kW Engineering
//
// The xeto compiler's own reading of each lib.xeto's depends: the Haxall 4.0.6 parser
// (XetoEnv.readAst) reads the pragma, so every string form, comment and heredoc is lexed by the compiler itself.
// It resolves nothing, so a plant naming a lib that is not installed still reads.
//
//   fan src/gen/xeto_depends.fan <file.xeto>...
//
// Prints one JSON object per file: {"file", "depends": [lib names in order], "versions": [each one's versions
// constraint as written, null where it has none]} or {"file", "error"}.
// check_open_libs.compiler_depends runs it; test_open_libs.py holds the hand reader to it.
//
using xeto
using haystack
using util

class XetoDepends
{
  Void main(Str[] args)
  {
    env := XetoEnv.cur
    ns := env.resolveNamespace(["sys"])
    args.each |path|
    {
      Str:Obj? row := ["file": path]
      try
      {
        ast := env->readAst(ns, File.os(path).readAllStr, Etc.dict0) as Dict
        deps := ast["depends"] as Dict
        Str[] libs := [,]
        Str?[] vers := [,]
        if (deps != null)
        {
          names := Str[,]
          deps.each |v, n| { if (n.startsWith("_")) names.add(n) }
          names.sort |a, b| { a[1..-1].toInt <=> b[1..-1].toInt }
          names.each |n| { d := deps[n] as Dict; libs.add(d->lib.toStr); vers.add(d["versions"]?.toStr) }
        }
        row["depends"] = libs
        row["versions"] = vers
      }
      catch (Err e) row["error"] = e.toStr
      echo(JsonOutStream.writeJsonToStr(row))
    }
  }
}
