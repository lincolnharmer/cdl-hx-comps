//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using xeto
using haystack

**
** The pod and its Axon func lib depend on open code only. The test reads
** the source tree named by the environment variable CDL_RESOLVE_SRC (the
** repo's `src/` directory): `build.fan` depends, every `using` line of the
** pod, and the depends of `kw.cdl.resolve`, each against an allow-list,
** and refuses any text naming a kW product lib or ontology anywhere in
** them. A planted violation must turn each check red.
**
class DependencyGuardTest : Test
{
  ** Fantom and Haxall pods only
  static const Str[] podAllow := ["sys", "concurrent", "util", "xeto", "haystack", "axon", "hx", "hxComps", "build"]

  ** Open libs only, plus the platform libs an Axon function needs
  static Bool libAllowed(Str n)
  {
    if (["sys", "sys.comp", "hx.comps", "axon", "hx"].contains(n)) return true
    if (n == "kw.cdl" || n.startsWith("kw.cdl.")) return true
    if (n == "ph" || n.startsWith("ph.")) return true
    return false
  }

  ** The text no source file may hold, built so this file does not hold it
  static Str[] forbidden() { ["kw" + ".ph", "kw" + ".spe" + "cta", "kw" + "spe" + "cta", "spe" + "cta"] }

  File srcDir()
  {
    path := Env.cur.vars["CDL_RESOLVE_SRC"] ?: throw Err("set CDL_RESOLVE_SRC to the repo's src directory")
    dir := File.os(path).normalize
    if (!dir.isDir) dir = dir.uri.plusSlash.toFile
    if (!(dir + `fan/cdlResolve/build.fan`).exists) throw Err("no fan/cdlResolve/build.fan under $dir")
    return dir
  }

  ** Every violation in a pod directory and a func lib directory
  static Str[] violations(File podDir, File libDir)
  {
    acc := Str[,]
    build := (podDir + `build.fan`).readAllStr
    m := Regex<|depends\s*=\s*\[([^\]]*)\]|>.matcher(build)
    if (!m.find) acc.add("build.fan declares no depends")
    else
    {
      q := Regex<|"([A-Za-z0-9_]+)|>.matcher(m.group(1))
      while (q.find) { p := q.group(1); if (!podAllow.contains(p)) acc.add("build.fan depends on $p") }
    }
    files := File[,]
    podDir.walk |f| { if (!f.isDir) files.add(f) }
    libDir.walk |f| { if (!f.isDir) files.add(f) }
    files.each |f|
    {
      text := f.readAllStr
      lower := text.lower
      forbidden.each |s| { if (lower.contains(s)) acc.add("${f.name} names $s") }
      if (f.ext == "fan")
        text.splitLines.each |line|
        {
          u := Regex<|^\s*using\s+(\[\w+\]\s*)?([A-Za-z0-9_.]+)|>.matcher(line)
          if (!u.find) return
          if (u.group(1) != null) { acc.add("${f.name} uses " + u.group(1).trim + u.group(2)); return }
          if (!podAllow.contains(u.group(2))) acc.add("${f.name} uses ${u.group(2)}")
        }
    }
    lib := (libDir + `lib.xeto`).readAllStr
    dm := Regex<|lib:\s*"([^"]+)"|>.matcher(lib)
    while (dm.find) { n := dm.group(1); if (!libAllowed(n)) acc.add("kw.cdl.resolve depends on $n") }
    return acc
  }

  ** Wrong behaviour caught: the pod or its func lib gaining a dependency on
  ** a kW product pod or lib, or a kW ontology name creeping into the source.
  Void testOpenOnly()
  {
    src := srcDir
    v := violations(src + `fan/cdlResolve/`, src + `xeto/kw.cdl.resolve/`)
    verifyEq(v, Str[,])
    // the compiled pod agrees with build.fan
    Pod.of(this).depends.each |d| { verify(podAllow.contains(d.name), "pod depends on $d.name") }
  }

  ** Wrong behaviour caught: a guard that passes whatever it reads. Each
  ** planted violation, in a copy of the source, must be reported.
  Void testPlantedViolationsTurnRed()
  {
    src := srcDir
    tmp := Env.cur.tempDir + `cdlResolveGuard/`
    tmp.delete
    pod := tmp + `pod/`
    lib := tmp + `lib/`
    (src + `fan/cdlResolve/`).copyTo(pod)
    (src + `xeto/kw.cdl.resolve/`).copyTo(lib)
    try
    {
      verifyEq(violations(pod, lib), Str[,])

      b := pod + `build.fan`
      orig := b.readAllStr
      b.out.print(orig.replace("\"hxComps 4.0\"]", "\"hxComps 4.0\", \"" + "kw" + "Spe" + "cta 1.0\"]")).close
      verifyPlanted(pod, lib, "build.fan depends on " + "kw" + "Spe" + "cta")
      b.out.print(orig).close

      f := pod + `fan/Planted.fan`
      f.out.print("using " + "kw" + "Spec" + "ta\nclass Planted {}\n").close
      verifyPlanted(pod, lib, "Planted.fan uses " + "kw" + "Spec" + "ta")
      f.delete

      // FFI is not open Fantom or Haxall code
      f.out.print("using [java] java.lang\nclass Planted {}\n").close
      verifyPlanted(pod, lib, "Planted.fan uses [java]java.lang")
      f.delete

      // forbidden text anywhere, in any case, comments included
      f.out.print("// reads the " + "SPE" + "CTA runtime map\nclass Planted {}\n").close
      verifyPlanted(pod, lib, "Planted.fan names " + "spe" + "cta")
      f.delete

      l := lib + `lib.xeto`
      lorig := l.readAllStr
      l.out.print(lorig.replace("{ lib: \"hx\" }", "{ lib: \"hx\" }\n    { lib: \"" + "kw" + ".ph\" }")).close
      verifyPlanted(pod, lib, "kw.cdl.resolve depends on " + "kw" + ".ph")
      l.out.print(lorig).close

      verifyEq(violations(pod, lib), Str[,])
    }
    finally tmp.delete
  }

  private Void verifyPlanted(File pod, File lib, Str want)
  {
    v := violations(pod, lib)
    verify(v.contains(want), "planted '$want' not reported: $v")
  }
}
