#! /usr/bin/env fan
//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

using build

**
** Build: cdlResolve
**
** The pod depends on Fantom and Haxall pods only. DependencyGuardTest
** reads this list and every using line against its allow-list.
**
class Build : BuildPod
{
  new make()
  {
    podName = "cdlResolve"
    summary = "Resolves one configured CDL sequence into a flat hx.comps comp graph"
    version = Version("0.1.0")
    meta    = ["org.name":     "kW Engineering",
               "license.name": "Academic Free License 3.0",
               "vcs.name":     "Git"]
    depends = ["sys 1.0",
               "concurrent 1.0",
               "util 1.0",
               "xeto 4.0",
               "haystack 4.0",
               "axon 4.0",
               "hx 4.0",
               "hxComps 4.0"]
    srcDirs = [`fan/`, `test/`]
    resDirs = [`test/res/`]
    index   = ["xeto.bindings": "kw.cdl.resolve"]
    docApi  = true
  }
}
