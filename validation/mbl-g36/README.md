# Guideline 36 validation against MBL 14.0.0

This harness replays the Guideline 36 controller validation models of the Modelica Buildings Library (MBL) 14.0.0 through `cdlResolve` and Haxall's `hx.comps` engine, and compares every recorded output with MBL's own Dymola reference results.

The repository holds no MBL data. The harness downloads the MBL 14.0.0 release, checks its SHA-256, and derives everything from it at run time: the validation models' input signals, the controller parameters, the block defaults, Dymola's output interval and the reference results.

# Result

We replayed all 17 controller instances in MBL 14.0.0's 14 air-side Guideline 36 controller validation models (AHU, fan-coil and terminal-unit; the plant controllers were not run) through `cdlResolve` and `hx.comps` at a 0.1 s step. Of the 158 outputs MBL's reference records (101 samples each), 131 agree with the Dymola reference within 1e-5 x max(1, |ref|) at every sample. All 158 agree within 1e-3 x max(1, |ref|) at every sample, which is the default tolerance of the BuildingsPy regression tester that MBL's CI runs, applied pointwise. Of the 27 that differ, 5 are explained by step-size discretization or a documented `hx.comps` departure, and 22, up to 6.5e-4, are not yet explained. A one-step timing lag would show against these references in only 24 of the 158 outputs, and all 24 are among the 27 that differ.

`run.sh` reproduces the counts 158, 131, 27, 24 and the 1e-3 result, and prints the largest difference of each output that differs. The split of the 27 into 5 explained and 22 unexplained comes from separate analysis (step halving and exact solutions of the CDL equations) that this harness does not include. The documented departures are the `departures` of each `CdlClass` in `kw.cdl` ([Blocks](../../src/xeto/kw.cdl.doc/Blocks.md)).

# Prerequisites

- **Haxall with the `hx.comps` additions.** The libraries and the resolver need Haxall main after the v4.0.7 release with haxall pull requests #138 to #152 applied. Haxall v4.0.7 alone is not enough. Build it from source as [Haxall's build instructions](https://haxall.io/doc/docHaxall/Build) describe, from a branch of main that merges those pull requests. You need two things from that build: the Fantom installation that runs it (`FAN_HOME`) and the path entries of its environment (`HX_ENV_PATH`, below).
- **Java.** Whatever your Haxall build runs on. The published counts were made on JDK 17. Fantom reads the JVM options from `$FAN_HOME/etc/sys/config.props`; the replays ran with `java.options=-Xmx3g`.
- **Python 3 with numpy.** The published counts were made with Python 3.14 and numpy 2.4.
- **bash.** On Windows, Git Bash.
- **Network access** to github.com for the MBL download (a 180 MB zip).
- **Time.** About one hour for all 17 instances at 0.1 s on one core. The two multi-zone AHU instances take under a minute each; most others take two to five minutes.

# Running

1. Fetch MBL 14.0.0 into a directory of your choice. On Windows keep that directory's path short (the script says how short), because the deepest MBL file path is long.

   ```
   python fetch_mbl.py <mbl dir>
   ```

   It downloads `Buildings-v14.0.0.zip` from the MBL release on GitHub, refuses it unless its SHA-256 is `e088afbb9582df183d978bd94615e209c714123130b84c20dd7d3593a6da31ad`, extracts the parts the harness reads, and prints the directory to use as `MBL_HOME`.

2. Build the libraries and the resolver into a Haxall path environment under a work directory:

   ```
   export FAN_HOME=<your Fantom installation>
   export HX_ENV_PATH='<entry>;<entry>;...'
   bash build.sh <work dir>
   ```

   `HX_ENV_PATH` lists, separated by `;`, the directories of your Haxall environment that hold its pods (`lib/fan`) and xeto libraries (`lib/xeto`, `src/xeto`), in the order your own `fan.props` names them: typically your Haxall build directory, then the Project Haystack `xeto` and `haystack-defs` directories it uses. `build.sh` writes `<work dir>/env/fan.props` with the work environment first and those entries after it, copies `kw.cdl`, `kw.cdl.g36.common`, `kw.cdl.g36.ahu`, `kw.cdl.g36.terminal`, `kw.cdl.resolve` and the `cdlResolve` pod source into it, and compiles them with `fan xeto build` and the pod's `build.fan`.

3. Replay and compare:

   ```
   export MBL_HOME='<the directory fetch_mbl.py printed>'
   bash run.sh <work dir> all
   ```

   or name instances from `instances.txt`, such as `bash run.sh <work dir> coolingOnly`. Each instance runs in its own JVM, one after another. `STEP` sets another replay step; the published counts are for the default, 0.1 s.

`summarize.py <run>...` prints the totals again for runs already made, for example `python summarize.py coolingOnly-0.1s` with `MBL_HOME` and `G36_WORK=<work dir>` set.

# What it does

For each instance, `gen_inputs.py` reads the validation model's `.mo` (`mo.py`, a small Modelica reader that refuses what it does not understand) and rebuilds its source network:

- Every open-loop source block (constants, ramps, sines, pulses, unit delays, comparisons, timers, conversions, the occupancy schedule) is evaluated on the step grid t = k h as the CDL block defines it. A parameter the instance does not set takes the default from the block's own `.mo`. The controller inputs it drives go to `inputs.csv`.
- Blocks downstream of a controller output (the validation model's own `Not`, `Timer` and `Latch`) close loops back into the controller. The driver runs them in MBL's semantics on each step's outputs, so a loop through the validation model carries one step of delay. A closed-loop input starts from the reference's first sample where the reference records it, else from false or 0.
- The controller's parameters are the modifiers the validation model sets, evaluated from the model's own parameters.
- Dymola's raw output interval comes from the model's `.mos`. The validation model's own time events (pulse edges, ramp and sine start and end, sample instants, changes of its Boolean and Integer sources) go into the scenario.

`G36Replay.fan` resolves the controller with `CdlResolver` into one flat `hx.comps` graph, loads it into a `CompSpace`, and steps it: apply the inputs for this step, move the clock to t, execute the comp space once, read the outputs, update the feedback blocks. It writes the outputs on every step near a reference sample, a raw Dymola output point or an event (`trace.csv`), every change of a Boolean or Integer output or Boolean input (`changes.csv`), and every change of every Boolean comp in the graph (`events.csv`). It also writes the resolved graph (`graph.xeto`).

`compare.py` forms the comp's value at each reference sample the way BuildingsPy formed the reference: Dymola's raw output (the regular points plus every event, holding the event's left limit), resampled linearly onto the 101-point reference grid. Each sample of each output is then:

- **strict**: |comp - ref| <= 1e-5 x max(1, |ref|) for a Real; exact for a Boolean or Integer (within 1e-6 where the reference interpolates between raw points).
- **window**: not strict, but a logged event lies within one step of a raw point the value is formed from, and the reference lies within the range the comp value takes when those raw points move by one step (Real), or the comp changed to the reference value within one step (Boolean, Integer).
- **mismatch**: anything else.

Independently, each sample passes the **funnel** check when |comp - ref| <= 1e-3 x max(1, |ref|). An output agrees within 1e-5 when every sample is strict, and within 1e-3 when every sample passes the funnel check.

`lagpower.py` asks how small a timing lag each output's reference could reveal: for a Real, the smallest tolerance over slope at any sample away from an event; for a Boolean or Integer, the shortest time from one of its changes to the next raw output point. `summarize.py` counts the outputs where a lag of one step would show and checks whether each is among the outputs that are not strict. A lag can only explain a difference where the reference can see one.

# Output

`run.sh` writes `<work dir>/runs/<name>-<step>s/` per instance:

| File | Content |
|-|-|
| `scenario.json` | the controller, its parameters, the step, the feedback blocks, the reference grid and the events |
| `inputs.csv`, `input-check.txt` | the open-loop inputs, and each one the reference records checked against it |
| `trace.csv`, `changes.csv`, `events.csv` | the replay, as above |
| `graph.xeto`, `driver.txt`, `run.log` | the resolved graph, the harness revision, the replay log |
| `compare.txt` | per recorded column: largest difference and where, counts of strict, window and mismatch samples, the funnel count, then every mismatch with its time, comp value and reference value |

These files hold values derived from MBL. Do not commit them here.

Then it prints, per instance, its outputs and how many are strict, window, mismatch and funnel-ok, with each differing output as `name(samples, max |comp - ref|)`; then the totals; then:

```
outputs                                                      158
within 1e-5 x max(1, |ref|) at every sample (strict)         131
within 1e-3 x max(1, |ref|) at every sample (funnel)         158
outputs whose reference would reveal a one-step lag          24, of which 24 are among the 27 not strict
```

# Limits

- The plant controllers and the subsequence validation models are not part of this result. `ThermalZones.Validation.ControlLoops` is not one of the 17.
- Only outputs count. A reference also records inputs and internal signals; `compare.txt` lists them, and `summarize.py` leaves them out.
- The funnel check is pointwise on the reference grid. BuildingsPy's own funnel builds a tube with a time tolerance as well; this harness does not.
- At 0.1 s the comparison is between a discrete-time replay and a variable-step Dymola solution. The event window exists for that: Dymola stores an event's left limit at the event time, and a replay step can land on either side of it.
