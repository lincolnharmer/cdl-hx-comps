#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
# The class-to-comp table, hand-entered from the sources. classmap.py checks it and writes class-map.json.
NC = 'hx.comps::NumberConst'
BC = 'hx.comps::BoolConst'
SB2B = 'hx.comps::StatusBoolToBool'
SN2N = 'hx.comps::StatusNumberToNumber'
SEC = 'Real seconds to Duration (n sec)'
R2F = 'Real to Float'
I2I = 'Integer to Int'

T = {}
def add(name, grade, comp=None, conn=None, params=None, fixed=None, unused=None, sem=None, ev=None, common=None, keep=None,
        departures=None, requires=None, **kw):
    # `unused` names comp inputs and outputs that stay unlinked. A comp slot that is not transient is configuration,
    # and `keep` names each one left at the comp default, with the reason. classmap.py refuses any other config slot
    # that no connector, parameter or fixed value sets.
    # `departures` names each way the comp behaves differently from MBL that a G36 sequence can see. The generator
    # carries them into the class's CdlClass instance.
    # `requires` holds what the generator must do beyond the renames, as fields it reads:
    #   linkAlways: {input: value}, an input the comp needs linked; where CDL leaves it unconnected the generator
    #               links a constant of that value
    #   loopCut:    [input, ...], inputs whose incoming link carries `loopCut`
    #   whenNull:   {input: value}, the `whenNull` the generator sets on the input's feed
    #   writeWhenUnit: [param, ...], parameters the generator writes explicitly, at the instance's binding or the CDL
    #               default, whenever their unit group carries a unit, so a resolver sees and converts them
    #   compoundGain: {comp, connectors, gain, per, perGroup, zero, fixed}, the comp an instance runs on instead
    #               when its gain parameter is bound to a unit the unit database lacks (s/K): a Line through (0, 0)
    #               and (1 <denominator>, gain <numerator>). Its output takes the numerator unit. Each point arrives
    #               through a NumberConst feed. `per` (1 <denominator>) is a difference in the unit group of the CDL
    #               connector `perGroup`: a resolver converts it with that group, and the comp does not convert it
    T[name] = dict(grade=grade, comp=comp, connectors=conn or {}, params=params or {}, fixed=fixed or {},
                   unused=unused or [], keep=keep or {}, departures=departures or [], requires=requires or {},
                   sem=sem or [], ev=ev or [], common=common or [], **kw)

U1 = {'u': 'inA', 'y': 'out'}
B2 = {'u1': 'inA', 'u2': 'inB', 'y': 'out'}
SW = {'u1': 'inTrue', 'u2': 'inSwitch', 'u3': 'inFalse', 'y': 'out'}
QUADU = ['inC', 'inD']
RAD_OUT = 'CDL `y` is in rad. The comp writes a unitless Number (UnaryMath.fan `Number(a.toFloat.asin)` and peers).'
RAD_IN = 'CDL `u` is in rad. UnaryMath ignores the input unit, so an input in degrees is not converted.'

# ---- unary math (Reals and Integers)
for n, c, extra in [('IntegersAbs','AbsValue',[]),('RealsAbs','AbsValue',[]),('RealsAcos','ArcCosine',[RAD_OUT]),
    ('RealsAsin','ArcSine',[RAD_OUT]),('RealsAtan','ArcTangent',[RAD_OUT]),('RealsCos','Cosine',[RAD_IN]),
    ('RealsSin','Sine',[RAD_IN]),('RealsTan','Tangent',[RAD_IN]),('RealsExp','Exponential',[]),
    ('RealsLog','LogNatural',[]),('RealsLog10','LogBase10',[]),('RealsSqrt','SquareRoot',[])]:
    add(n, 'native', 'hx.comps::'+c, U1, common=['unary'], sem=extra, ev=['math.xeto:17-20 (UnaryMath.inA)', 'UnaryMath.fan onExecute'])

# ---- binary math
for n, c in [('IntegersSubtract','Subtract'),('RealsSubtract','Subtract'),('RealsDivide','Divide')]:
    add(n, 'native', 'hx.comps::'+c, B2, common=['binary'], ev=['math.xeto:63-69 (BinaryMath.inA, inB)', 'BinaryMath.fan onExecute'],
        sem=(['A zero `inB` gives the Fantom float result (INF or NaN) with no fault. MBL Divide has no guard either.'] if c=='Divide' else []))
add('RealsAtan2', 'native', 'hx.comps::ArcTangent2', B2, common=['binary'],
    sem=['`out` is unitless where CDL `y` is in rad, and 0 at the origin (math.xeto:130-132).',
         '`inB` converts to the unit of `inA` by scale only. A temperature difference against a temperature faults (math.xeto:120-127).'],
    ev=['math.xeto:117-133', 'haxall pull request #150'])
add('RealsModulo', 'native', 'hx.comps::FlooredModulus', B2, common=['binary'],
    sem=['Floored, with the sign of `inB`, as CDL. `Modulus` truncates and is the wrong comp (math.xeto:135-138).',
         'A zero `inB` or an infinite input gives NaN (math.xeto:145-147).'],
    ev=['math.xeto:135-149', 'haxall pull request #150'])

# ---- quad math and logic (2 of 4 inputs used)
for n, c in [('IntegersAdd','Add'),('RealsAdd','Add'),('IntegersMultiply','Multiply'),('RealsMultiply','Multiply'),
             ('IntegersMax','Maximum'),('RealsMax','Maximum'),('IntegersMin','Minimum'),('RealsMin','Minimum'),('RealsAverage','Average')]:
    add(n, 'native', 'hx.comps::'+c, B2, unused=QUADU, common=['quad'], ev=['math.xeto:86-98 (QuadMath)', 'QuadMath.fan onExecute'],
        sem=(['CDL Average is (u1+u2)/2. With one input skipped, `out` is the other input, not half of it.'] if c=='Average' else []))
for n, c in [('LogicalAnd','And'),('LogicalOr','Or'),('LogicalXor','Xor')]:
    add(n, 'native', 'hx.comps::'+c, B2, unused=QUADU, common=['quadLogic'], ev=['logic.xeto:23-35 (QuadLogic)', 'QuadLogic.fan onExecute'],
        sem=(['Xor needs 2 non-null inputs (`minInputs := 2`), so one null input gives null `out`, where And and Or compute from the other input.'] if c=='Xor' else []))
add('LogicalNot', 'native', 'hx.comps::Not', {'u': 'in', 'y': 'out'},
    sem=['An invalid `in` gives false with its status, not the negation (logic.xeto:15, Logic.fan Not.onExecute).', 'A null `in` gives null `out`.'],
    ev=['logic.xeto:15-18', 'Logic.fan Not.onExecute'])

# ---- comparisons
for n, c in [('IntegersEqual','Equal'),('IntegersGreater','GreaterThan'),('IntegersGreaterEqual','GreaterThanEqual'),
             ('IntegersLess','LessThan'),('IntegersLessEqual','LessThanEqual')]:
    add(n, 'native', 'hx.comps::'+c, B2, common=['compare'] + (['equalUnit'] if c=='Equal' else []), ev=['logic.xeto:47-53 (Comparison)', 'Comparison.fan onExecute'])
for n, c in [('IntegersGreaterEqualThreshold','GreaterThanEqual'),('IntegersGreaterThreshold','GreaterThan'),
             ('IntegersLessEqualThreshold','LessThanEqual'),('IntegersLessThreshold','LessThan')]:
    add(n, 'nativeParams', 'hx.comps::'+c, U1, params={'t': {'slot': 'inB', 'feed': NC, 'convert': 'Integer to StatusNumber on NumberConst.out'}},
        common=['compare', 'transientFeed'], ev=['logic.xeto:47-53 (Comparison.inB is transient)', 'Comparison.fan onExecute'])

# ---- parameter math
add('IntegersAddParameter', 'nativeParams', 'hx.comps::Add', U1, params={'p': {'slot': 'inB', 'feed': NC, 'convert': 'Integer to StatusNumber on NumberConst.out'}},
    unused=QUADU, common=['quad', 'transientFeed'], ev=['math.xeto:86-101', 'QuadMath.fan onExecute'])
add('RealsAddParameter', 'nativeParams', 'hx.comps::Add', U1, params={'p': {'slot': 'inB', 'feed': NC}},
    unused=QUADU, common=['quad', 'transientFeed'], ev=['math.xeto:86-101', 'QuadMath.fan onExecute'])
add('RealsMultiplyByParameter', 'nativeParams', 'hx.comps::Multiply', U1, params={'k': {'slot': 'inB', 'feed': NC}},
    unused=QUADU, common=['quad', 'transientFeed'], ev=['math.xeto:86-104', 'QuadMath.fan onExecute'],
    requires={'compoundGain': {'comp': 'hx.comps::Line', 'connectors': {'u': 'in', 'y': 'out'}, 'gain': 'inF2',
                               'per': 'inX2', 'perGroup': 'u', 'zero': ['inX1', 'inF1'],
                               'fixed': {'limitBelow': False, 'limitAbove': False}}},
    departures=['A gain bound to a unit the unit database lacks (s/K, the change rate chaRat of '
                'Generic.TimeSuppression) runs on `Line` instead, through (0, 0) and (1 K, chaRat s). Multiply would '
                'give the product the unit of `u`, K, and a K value then meets seconds in a comparison and faults. '
                'Line gives `out` the unit of its second axis, seconds. Its first axis takes the unit of `u`, and '
                'Line does not convert a difference against an absolute value, so the resolver converts the point '
                '1 K with the unit group of `u`, as a difference (1.8 Fahrenheit degrees on a Fahrenheit building), '
                'and writes chaRat in seconds unconverted. 540 s per kelvin then acts as 300 s per Fahrenheit '
                'degree.'])

# ---- switches and conversions
add('IntegersSwitch', 'native', 'hx.comps::NumberSwitch', SW, common=['switch'], ev=['switches.xeto:44-57', 'Switch.fan ValSwitch.onExecute'])
add('RealsSwitch', 'native', 'hx.comps::NumberSwitch', SW, common=['switch'], ev=['switches.xeto:44-57', 'Switch.fan ValSwitch.onExecute'])
add('LogicalSwitch', 'native', 'hx.comps::BoolSwitch', SW, common=['switch'], ev=['switches.xeto:28-41', 'Switch.fan ValSwitch.onExecute'])
for n, t, f in [('ConversionsBooleanToInteger','integerTrue','integerFalse'),('ConversionsBooleanToReal','realTrue','realFalse')]:
    add(n, 'nativeParams', 'hx.comps::NumberSwitch', {'u': 'inSwitch', 'y': 'out'},
        params={t: {'slot': 'inTrue', 'feed': NC}, f: {'slot': 'inFalse', 'feed': NC}}, common=['switch'],
        sem=['`inTrue` and `inFalse` are not transient (switches.xeto:50, 53), so a direct set would also be saved. The NumberConst feed follows the existing binding.'],
        ev=['switches.xeto:44-57', 'Switch.fan ValSwitch.onExecute'])
add('ConversionsIntegerToReal', 'link', None, {}, link={'from': 'u', 'to': 'y'}, dropped={},
    sem=['CDL Integer and Real both ride StatusNumber, so the wire carries the value unchanged.'], ev=['math.xeto:13 (Math.out is StatusNumber)'])
add('ConversionsRealToInteger', 'native', 'hx.comps::Round', {'u': 'in', 'y': 'out'}, fixed={'n': 0},
    sem=['`n` must be 0. That is its default (math.xeto:200), so nothing is written unless a default changes.',
         'Half rounds away from zero, as MBL RealToInteger (math.xeto:181-185).',
         '`out` is a whole Number that keeps the unit of `in` (math.xeto:186-187). CDL Integer has no unit, and `Equal` downstream compares units.'],
    common=['roundRules'], ev=['math.xeto:181-201', 'haxall pull request #150'])
add('RealsRound', 'nativeParams', 'hx.comps::Round', {'u': 'in', 'y': 'out'}, params={'n': {'slot': 'n', 'feed': 'set', 'convert': I2I}},
    sem=['CDL `n` has no default. The comp defaults it to 0 (math.xeto:200).',
         'CDL `n` is an Integer: kw.cdl (blocks.xeto:1244) and MBL 14 `Reals/Round.mo` line 4 type it `parameter Integer n`, so the mapping is Integer to Int.',
         'A zero result is positive zero (math.xeto:193-194).'],
    common=['roundRules'], ev=['math.xeto:181-201', 'haxall pull request #150', 'MBL 14 Buildings/Controls/OBC/CDL/Reals/Round.mo:4'])

# ---- constants
add('IntegersSourcesConstant', 'const', 'hx.comps::NumberConst', {'y': 'out'}, params={'k': {'slot': 'out', 'feed': 'set', 'convert': 'Integer to StatusNumber {val, status ok}'}},
    sem=['NumberConst has no behavior (Constants.fan). `out` is not transient, so the set value is saved (constants.xeto:19).'], ev=['constants.xeto:18-20', 'Constants.fan'])
add('RealsSourcesConstant', 'const', 'hx.comps::NumberConst', {'y': 'out'}, params={'k': {'slot': 'out', 'feed': 'set', 'convert': 'Real to StatusNumber {val, status ok}'}},
    sem=['NumberConst has no behavior (Constants.fan). `out` is not transient, so the set value is saved (constants.xeto:19).'], ev=['constants.xeto:18-20', 'Constants.fan'])
add('LogicalSourcesConstant', 'const', 'hx.comps::BoolConst', {'y': 'out'}, params={'k': {'slot': 'out', 'feed': 'set', 'convert': 'Boolean to StatusBool {val, status ok}'}},
    sem=['BoolConst has no behavior (Constants.fan). `out` is not transient, so the set value is saved (constants.xeto:14).'], ev=['constants.xeto:13-15', 'Constants.fan'])

# ---- discrete
SPC = {'slot': 'period', 'feed': 'set', 'convert': SEC}
add('DiscreteSampler', 'nativeParams', 'hx.comps::Sampler', {'u': 'in', 'y': 'out'}, params={'samplePeriod': SPC},
    sem=['Direct feedthrough. Never cut a loop at it (sampling.xeto:70-71).', 'An instant takes the value of `in` on the first execute at or after it (sampling.xeto:38-39).'],
    common=['sampleGrid', 'nullHold', 'noDefaultPeriod'], ev=['sampling.xeto:57-72', 'haxall pull request #146'])
add('DiscreteZeroOrderHold', 'nativeParams', 'hx.comps::ZeroOrderHold', {'u': 'in', 'y': 'out'}, params={'samplePeriod': SPC},
    sem=['A loop may be cut at it with a `loopCut` marker on the link into `in` (sampling.xeto:78-82). The spec carries `loopBreak` (sampling.xeto:86).',
         'Uncut, `out` is null before the first sample (sampling.xeto:83-85). CDL holds `y = pre(ySample)` from the start.',
         'Cut, a null, invalid or NaN `in` takes no sample and `out` is 0 and ok until the first valid `in` (sampling.xeto:51-56).'],
    common=['sampleGrid', 'noDefaultPeriod'], ev=['sampling.xeto:57-86', 'haxall pull request #146', 'haxall pull request #147'])
add('DiscreteFirstOrderHold', 'nativeParams', 'hx.comps::FirstOrderHold', {'u': 'in', 'y': 'out'}, params={'samplePeriod': SPC},
    sem=['Until the first instant `out` is the first `in` (sampling.xeto:91-92).', 'Between instants `out` updates every second (sampling.xeto:92-93), not continuously.',
         'Cut in a loop, the line starts from 0 and is off CDL by up to one cycle of slope (sampling.xeto:98-102).'],
    common=['sampleGrid', 'noDefaultPeriod'], ev=['sampling.xeto:57-66, 88-103', 'haxall pull request #146'])
add('DiscreteUnitDelay', 'nativeParams', 'hx.comps::UnitDelay', {'u': 'in', 'y': 'out'},
    params={'samplePeriod': SPC, 'y_start': {'slot': 'yStart', 'feed': 'set'}}, requires={'loopCut': ['u']},
    sem=['The link into `in` carries a `loopCut` marker, in a loop or not (sampling.xeto:110-114), set by `requires.loopCut`. Uncut, a loop through it depends on creation order.',
         'It captures `in` on the cycle after an instant and emits it at the next (sampling.xeto:107-108).',
         'A null, invalid or NaN `in` keeps the last capture and `out` stays ok (sampling.xeto:114-118).'],
    common=['sampleGrid', 'noDefaultPeriod'], ev=['sampling.xeto:105-131', 'haxall pull request #147'])
add('DiscreteTriggeredSampler', 'nativeParams', 'hx.comps::TriggeredSampler', {'u': 'in', 'trigger': 'trigger', 'y': 'out'},
    params={'y_start': {'slot': 'yStart', 'feed': 'set'}}, common=['triggered'], ev=['triggered.xeto:22-39', 'haxall pull request #146'])
add('DiscreteTriggeredMax', 'native', 'hx.comps::TriggeredMax', {'u': 'in', 'trigger': 'trigger', 'y': 'out'},
    sem=['The first execute sets `out` to `in`, not its absolute value (triggered.xeto:42-43), as MBL `y = u` at initialization.'],
    common=['triggered'], ev=['triggered.xeto:22-31, 41-45', 'haxall pull request #146', 'MBL 14 Discrete/TriggeredMax.mo initial equation `y=u`'])
add('DiscreteTriggeredMovingMean', 'nativeParams', 'hx.comps::TriggeredMovingMean', {'u': 'in', 'trigger': 'trigger', 'y': 'out'},
    params={'n': {'slot': 'n', 'feed': 'set', 'convert': I2I}},
    sem=['The first execute takes a sample, and until `n` samples the mean is over those taken (triggered.xeto:48-49).', 'A change of `n` starts the mean again (triggered.xeto:51).',
         'CDL `n` has no default. The comp defaults it to 1 (triggered.xeto:55).'],
    common=['triggered'], ev=['triggered.xeto:22-31, 47-56', 'haxall pull request #146'])

# ---- hysteresis comparators
HYS = {'h': {'slot': 'deadband', 'feed': 'set'}, 'pre_y_start': {'slot': 'initOut', 'feed': 'set'}}
HSEM = ['A non-zero `h` gives the CDL hysteresis. With `h` 0 the comp gives the plain comparison, as CDL does with no hysteresis instance.',
        'An invalid input holds the state and `out` with the merged status, where `Comparison` writes false (logic.xeto:78-81).',
        'Mismatched `inA` and `inB` units fault and hold `out`.',
        '`deadband` is read in the unit of `inB` or its delta unit (logic.xeto:93-94).']
add('RealsGreater', 'nativeParams', 'hx.comps::GreaterThanHys', B2, params=HYS, sem=['`out` turns true when A > B and false when A <= B - deadband (logic.xeto:101-103), as MBL.'] + HSEM,
    ev=['logic.xeto:86-104', 'haxall pull request #144'])
add('RealsLess', 'nativeParams', 'hx.comps::LessThanHys', B2, params=HYS, sem=['`out` turns true when A < B and false when A >= B + deadband (logic.xeto:106-108), as MBL.'] + HSEM,
    ev=['logic.xeto:86-99, 106-109', 'haxall pull request #144'])
add('RealsGreaterThreshold', 'nativeParams', 'hx.comps::GreaterThanHys', U1, params=dict(HYS, t={'slot': 'inB', 'feed': NC}),
    sem=['The threshold arrives on `inB` from a linked NumberConst (logic.xeto:75-76, 102-103).'] + HSEM, common=['transientFeed'],
    ev=['logic.xeto:73-104', 'haxall pull request #144'])
add('RealsLessThreshold', 'nativeParams', 'hx.comps::LessThanHys', U1, params=dict(HYS, t={'slot': 'inB', 'feed': NC}),
    sem=['The threshold arrives on `inB` from a linked NumberConst (logic.xeto:75-76, 107-108).'] + HSEM, common=['transientFeed'],
    ev=['logic.xeto:73-99, 106-109', 'haxall pull request #144'])
add('RealsHysteresis', 'nativeParams', 'hx.comps::Hysteresis', {'u': 'in', 'y': 'out'},
    params={'uLow': {'slot': 'low', 'feed': 'set'}, 'uHigh': {'slot': 'high', 'feed': 'set'}, 'pre_y_start': {'slot': 'initOut', 'feed': 'set'}},
    sem=['`high` not above `low` is a fault (logic.xeto:114-115). MBL asserts uHigh > uLow at translation.', 'Limits whose units differ from each other or from `in` fault, where a unitless value fits any unit (logic.xeto:116-117).'],
    ev=['logic.xeto:111-130', 'haxall pull request #144'])

# ---- latches, edges, change
add('LogicalLatch', 'native', 'hx.comps::SetResetLatch', {'u': 'in', 'clr': 'inClear', 'y': 'out'},
    sem=['A rise of `inClear` wins over a rise of `in` on one execute (latches.xeto:46-47).', 'The first valid execute sets `out` to `in` and not `inClear` (latches.xeto:50-51), as MBL initializes `y`.',
         'A rise of a valid `inClear` clears even while `in` is null or invalid (latches.xeto:52-53).'],
    common=['nullHold'], ev=['latches.xeto:45-60', 'haxall pull request #145', 'MBL 14 Logical/Latch.mo initial equation `y = not clr and u`'])
add('LogicalToggle', 'native', 'hx.comps::Toggle', {'u': 'in', 'clr': 'inClear', 'y': 'out'},
    sem=['A rise of `inClear` sets `out` false and wins over a rise of `in` (latches.xeto:62-64).', 'The first valid execute sets `out` to `in` and not `inClear` (latches.xeto:66-67), as MBL `y = if clr then false else u` at initial().'],
    common=['nullHold'], ev=['latches.xeto:62-77', 'haxall pull request #145', 'MBL 14 Logical/Toggle.mo initial equation'])
for n, e in [('LogicalEdge', 'rising'), ('LogicalFallingEdge', 'falling'), ('LogicalChange', 'change')]:
    add(n, 'nativeParams', 'hx.comps::BoolEdge', {'u': 'in', 'y': 'out'}, params={'pre_u_start': {'slot': 'initPrev', 'feed': 'set'}},
        fixed={'edge': e}, common=['pulseOneExecute'],
        sem=['`edge` must be `%s`%s (logic.xeto:145).' % (e, ', its default' if e == 'rising' else ', not the default `rising`'),
             'After a restart the first valid execute compares `in` with `initPrev` again (logic.xeto:138-139).'],
        ev=['logic.xeto:132-156', 'haxall pull request #145'])
add('IntegersChange', 'nativeParams', 'hx.comps::NumberChange', {'u': 'in', 'y': 'out', 'up': 'up', 'down': 'down'},
    params={'pre_u_start': {'slot': 'initPrev', 'feed': 'set', 'convert': 'Integer to Number'}}, common=['pulseOneExecute'],
    sem=['The values compare as floats and the unit is ignored (logic.xeto:161-162).', 'A NaN `in` with a valid status, or a NaN `initPrev`, is a fault (logic.xeto:166-169).'],
    ev=['logic.xeto:158-183', 'haxall pull request #145'])
add('IntegersOnCounter', 'nativeParams', 'hx.comps::Counter', {'trigger': 'trigger', 'reset': 'reset', 'y': 'out'},
    params={'y_start': {'slot': 'initVal', 'feed': 'set', 'convert': I2I}},
    requires={'linkAlways': {'reset': False}},
    sem=['An unlinked `reset` keeps `out` null (util.xeto:144-145). `requires.linkAlways` has the generator link a BoolConst false wherever CDL leaves `reset` unconnected.',
         'A rise of `trigger` while `reset` is true goes to `initVal` (util.xeto:136-137), as MBL `when {trigger, reset} then y = if reset then y_start else pre(y)+1`.',
         'A null input sets `out` null and an invalid one holds it, both keeping the count (util.xeto:138-139).'],
    ev=['util.xeto:135-153', 'haxall pull request #145', 'MBL 14 Integers/OnCounter.mo'])

# ---- timers
add('LogicalTrueDelay', 'nativeParams', 'hx.comps::BoolDelay', {'u': 'in', 'y': 'out'},
    params={'delayTime': {'slot': 'onDelay', 'feed': 'set', 'convert': SEC}, 'delayOnInit': {'slot': 'delayOnInit', 'feed': 'set'}},
    fixed={'offDelay': '0sec'}, unused=['outNot'],
    sem=['`offDelay` must be set to 0sec. Its default is 1sec (timer.xeto:29), which would delay every fall by a second.',
         'CDL `delayTime` has no default. `onDelay` defaults to 1sec (timer.xeto:25).',
         'A change to a delay applies to a pending timer (timer.xeto:13-14).',
         'A null `in` sets `out` null and an invalid `in` holds it, keeping the timer state (timer.xeto:17-18).'],
    common=['ownClock'], ev=['timer.xeto:9-40', 'haxall pull request #141'])
add('LogicalTrueFalseHold', 'nativeParams', 'hx.comps::BoolHold', {'u': 'in', 'y': 'out'},
    params={'trueHoldDuration': {'slot': 'trueHold', 'feed': 'set', 'convert': SEC},
            'falseHoldDuration': {'slot': 'falseHold', 'feed': 'set', 'convert': SEC}},
    sem=['CDL defaults `falseHoldDuration` to `trueHoldDuration`. `falseHold` defaults to 0sec (timer.xeto:80-82). The generator must write `falseHold` = `trueHoldDuration` when the CDL instance leaves it at its default.',
         'A change of `in` passes at once unless a hold is running (timer.xeto:65-67).'],
    common=['ownClock', 'nullHold'], ev=['timer.xeto:64-86', 'haxall pull request #145'])
add('LogicalTimer', 'nativeParams', 'hx.comps::Timer', {'u': 'in', 'y': 'out', 'passed': 'passed'},
    params={'t': {'slot': 'threshold', 'feed': 'set', 'convert': SEC}},
    sem=['`out` carries the unit `s` (Timer.fan:58, 124), as CDL `y`.', 'While `in` is true, `out` refreshes once a second (timer.xeto:93-94), so `y` steps rather than ramps.',
         '`passed` turns true on the first cycle at or after the threshold, as MBL. ASHRAE 231 7.5.76 says after it.',
         'With a threshold of 0, `passed` stays false until `in` turns true, and a negative threshold acts as 0 (timer.xeto:91-92).'],
    # MBL Logical/Timer.mo:28 has pre(passed) = t <= 0; Timer.fan:106 has passedVal = u && threshold <= 0ns
    departures=['At start-up with `t` <= 0, MBL starts `passed` true while `u` is false. The comp starts `passed` false, so the two differ until `u` first turns true.'],
    common=['ownClock', 'nullHold'], ev=['timer.xeto:88-112', 'Timer.fan:58,106,124', 'MBL 14 Logical/Timer.mo:28', 'haxall pull request #145'])
add('LogicalTimerAccumulating', 'nativeParams', 'hx.comps::AccumTimer', {'u': 'in', 'reset': 'reset', 'y': 'out', 'passed': 'passed'},
    params={'t': {'slot': 'threshold', 'feed': 'set', 'convert': SEC}},
    requires={'linkAlways': {'reset': False}},
    sem=['An unlinked `reset` keeps both outputs null (timer.xeto:138-139). `requires.linkAlways` has the generator link a BoolConst false wherever CDL leaves `reset` unconnected.',
         'With a threshold of 0 or less, `passed` is true from the start and right after each reset (timer.xeto:116-118).',
         'A fall of `in` in the execute that reaches the threshold leaves `passed` false, as MBL does (timer.xeto:121-125).',
         'The total starts from 0 on the first valid execute and does not survive a restart (timer.xeto:130-131).',
         '`out` carries the unit `s` (AccumTimer.fan:74, 152).'],
    common=['ownClock'], ev=['timer.xeto:114-150', 'AccumTimer.fan:74,152', 'haxall pull request #145'])

# ---- sources with comps
add('LogicalSourcesSampleTrigger', 'nativeParams', 'hx.comps::SampleTrigger', {'y': 'out'},
    params={'period': {'slot': 'period', 'feed': 'set', 'convert': SEC}, 'shift': {'slot': 'shift', 'feed': 'set', 'convert': SEC}},
    sem=['`out` is true for one execute at each instant (sampling.xeto:9-10).', 'Instants on consecutive cycles keep `out` true, so a rise-triggered consumer sees one rise (sampling.xeto:18-21).',
         'A late cycle that passes several instants pulses once (sampling.xeto:18).', 'CDL `period` has no default. The comp defaults it to 1min (sampling.xeto:26).'],
    common=['sampleGrid'], ev=['sampling.xeto:9-33', 'haxall pull request #146'])
add('LogicalSourcesPulse', 'nativeParams', 'hx.comps::BoolPulse', {'y': 'out'},
    params={'width': {'slot': 'width', 'feed': 'set', 'convert': R2F}, 'period': {'slot': 'period', 'feed': 'set', 'convert': SEC},
            'shift': {'slot': 'shift', 'feed': 'set', 'convert': SEC}},
    sem=['Rises sit at `shift` plus each whole `period` from 1 Jan 1970 UTC (pulse.xeto:10-13). MBL aligns `t0` to `integer(time/period)*period + mod(shift, period)` (MBL Logical/Sources/Pulse.mo:35-36), the same grid when `time` is epoch seconds.',
         'Each execute sets `out` from where the clock falls, so a pulse or gap shorter than the cycle can be missed (pulse.xeto:15-16).',
         'CDL `period` has no default. The comp defaults it to 1min (pulse.xeto:27).'],
    common=['sampleGrid'], ev=['pulse.xeto:9-34', 'haxall pull request #151', 'MBL 14 Logical/Sources/Pulse.mo:35-36'])

# ---- continuous
add('RealsIntegratorWithReset', 'nativeParams', 'hx.comps::Integrator', {'u': 'in', 'trigger': 'inReset', 'y_reset_in': 'inResetVal', 'y': 'out'},
    params={'k': {'slot': 'k', 'feed': 'set'}, 'y_start': {'slot': 'yStart', 'feed': 'set'}},
    sem=['Each step is a trapezoid to the current `in`, so `out` has direct feedthrough from `in` where CDL has none (continuous.xeto:14-15). A loop through it needs a `loopCut` link.',
         'A reset while `inResetVal` is invalid or not finite waits until it is usable (continuous.xeto:18-19). A null `inResetVal` resets to `yStart` (continuous.xeto:31).',
         '`out` has no unit (continuous.xeto:22).', 'After a restart `out` starts again from `yStart` (continuous.xeto:22-23).'],
    common=['stall'], ev=['continuous.xeto:9-42', 'haxall pull request #148'])
add('RealsDerivative', 'nativeParams', 'hx.comps::Derivative', {'u': 'in', 'y': 'out',
        'k': {'slot': 'k', 'via': SN2N}, 'T': {'slot': 'timeConst', 'via': SN2N}},
    params={'y_start': {'slot': 'yStart', 'feed': 'set'}}, requires={'whenNull': {'k': 1, 'T': 1}},
    sem=['CDL `k` and `T` are input connectors. On the comp they are plain Number slots (continuous.xeto:49-50, 64-67).',
         'A signal reaches them through a StatusNumberToNumber feed, which drops the status. Its `whenNull` slot has no default (conversions.xeto:55-56). `requires.whenNull` sets it to 1 for both, the comp defaults of `k` and `timeConst` (continuous.xeto:64-67), so a null signal acts as an unlinked slot.',
         'Where the CDL source of `k` or `T` is a constant, the generator may set the slot directly instead.',
         '`timeConst` is in seconds unless it carries a time unit (continuous.xeto:66). A `timeConst` below 0 faults (continuous.xeto:55-56). CDL requires `T` at least 1E-13.',
         '`out` has no unit (continuous.xeto:58).'],
    common=['stall'], ev=['continuous.xeto:44-74', 'conversions.xeto:49-57', 'haxall pull request #148'])
add('RealsLimitSlewRate', 'nativeParams', 'hx.comps::SlewRateLimit', {'u': 'in', 'y': 'out'},
    params={'raisingSlewRate': {'slot': 'raisingSlewRate', 'feed': 'set'}, 'fallingSlewRate': {'slot': 'fallingSlewRate', 'feed': 'set'},
            'Td': {'slot': 'timeConst', 'feed': 'set', 'convert': SEC}, 'enable': {'slot': 'enable', 'feed': 'set'}},
    sem=['A null `fallingSlewRate` is minus `raisingSlewRate` and a null `timeConst` is `raisingSlewRate` times 10 s, the CDL defaults (continuous.xeto:100-106).',
         'Rates are in units of `in` per second unless they carry a time unit (continuous.xeto:96-97), matching CDL `1/s` on a unitless `u`.',
         'Each step is backward Euler to the current `in`, so `out` has direct feedthrough (continuous.xeto:83-85).'],
    common=['stall'], ev=['continuous.xeto:76-113', 'haxall pull request #148'])
add('RealsRamp', 'nativeParams', 'hx.comps::SlewRateLimit', {'u': 'in', 'y': 'out', 'active': {'slot': 'enable', 'via': SB2B}},
    params={'raisingSlewRate': {'slot': 'raisingSlewRate', 'feed': 'set'}, 'fallingSlewRate': {'slot': 'fallingSlewRate', 'feed': 'set'},
            'Td': {'slot': 'timeConst', 'feed': 'set', 'convert': SEC}},
    sem=['CDL defaults `Td` to `raisingSlewRate*0.001`. A null `timeConst` gives `raisingSlewRate*10` (continuous.xeto:104-105). The generator must write `timeConst` = `raisingSlewRate`*0.001 s when the CDL instance leaves `Td` at its default.',
         'CDL `active` is an input. The comp `enable` is a plain Bool slot, reached through a StatusBoolToBool feed (continuous.xeto:79-81). A null `active` then reads `whenNull`, false by default (conversions.xeto:27-28), so `out` follows `in`.',
         'MBL Ramp reinitializes the ramp to `u` on a rise of `active` and outputs `u` while inactive (MBL Reals/Ramp.mo equation). The comp gives `out = in` while disabled, so it starts from `in` on enable too.'],
    common=['stall'], ev=['continuous.xeto:76-113', 'conversions.xeto:21-29', 'haxall pull request #148', 'MBL 14 Reals/Ramp.mo equation section'])
add('RealsMovingAverage', 'nativeParams', 'hx.comps::MovingAverage', {'u': 'in', 'y': 'out'},
    params={'delta': {'slot': 'window', 'feed': 'set', 'convert': SEC}},
    sem=['Before a full window the elapsed time is guarded by 1E-10 s, as ASHRAE 231 7.5.24. MBL adds 1E-3 s, so the first seconds differ slightly (continuous.xeto:116-120).',
         'The comp keeps one entry per execute in the window (continuous.xeto:127). A long window at a short cycle holds many entries.',
         'CDL `delta` has no default. `window` defaults to 1min (continuous.xeto:137).'],
    common=['stall'], ev=['continuous.xeto:115-141', 'haxall pull request #148'])

# ---- PID
PIDP = {'controllerType': {'slot': 'controllerType', 'feed': 'set', 'convert': 'TypesSimpleController key to PidControllerType: P->p, PI->pi, PD->pd, PID->pid'},
        'k': {'slot': 'k', 'feed': 'set', 'convert': R2F}, 'Ti': {'slot': 'ti', 'feed': 'set', 'convert': SEC},
        'Td': {'slot': 'td', 'feed': 'set', 'convert': SEC}, 'r': {'slot': 'r', 'feed': 'set', 'convert': R2F},
        'yMax': {'slot': 'yMax', 'feed': 'set', 'convert': R2F}, 'yMin': {'slot': 'yMin', 'feed': 'set', 'convert': R2F},
        'Ni': {'slot': 'ni', 'feed': 'set', 'convert': R2F}, 'Nd': {'slot': 'nd', 'feed': 'set', 'convert': R2F},
        'xi_start': {'slot': 'xiStart', 'feed': 'set', 'convert': R2F}, 'yd_start': {'slot': 'ydStart', 'feed': 'set', 'convert': R2F},
        'reverseActing': {'slot': 'reverseActing', 'feed': 'set'}}
PSEM = ['Equal `yMin` and `yMax` give that value. MBL rejects them (util.xeto:170-171).',
        'Parameters are checked only for the terms the controller type uses (util.xeto:172).',
        'The comp executes every cycle with backward Euler steps and an implicit anti-windup, so its response depends on the cycle length.',
        'An invalid input holds the state and `out` and propagates the status. A non-finite input faults (util.xeto:174-182).']
PID_FLOAT = ('`k`, `r`, `yMax`, `yMin`, `xi_start`, `yd_start` and `y_reset` are Float slots, which carry no unit. `r` '
             'scales the control error, so on points that are not SI it must be converted into their difference unit '
             '(5 K is 9 Fahrenheit degrees), and the comp cannot catch a conversion that was missed. `r` is written on '
             'every loop whose setpoint carries a unit. Any `1/K` is provenance only and is never converted (in G36 '
             'every one is the `k` of a PID): converting `r` alone converts the loop.')
add('RealsPid', 'nativeParams', 'hx.comps::CdlPid', {'u_s': 'inSetpoint', 'u_m': 'inMeasurement', 'y': 'out'}, params=PIDP, unused=['inReset'],
    departures=[PID_FLOAT], requires={'writeWhenUnit': ['r']},
    keep={'yReset': '`inReset` stays unlinked, so the comp never reads `yReset`.'},
    sem=['`inReset` stays unlinked. A null `inReset` is no reset (util.xeto:163-164).'] + PSEM, common=['stall'],
    ev=['util.xeto:155-242', 'haxall pull request #149'])
add('RealsPidWithReset', 'nativeParams', 'hx.comps::CdlPid', {'u_s': 'inSetpoint', 'u_m': 'inMeasurement', 'trigger': 'inReset', 'y': 'out'},
    departures=[PID_FLOAT], requires={'writeWhenUnit': ['r']},
    params=dict(PIDP, y_reset={'slot': 'yReset', 'feed': 'set', 'convert': R2F}),
    sem=['CDL defaults `y_reset` to `xi_start`. `yReset` defaults to 0 (util.xeto:169-170). The generator must write `yReset` = `xi_start` when the CDL instance leaves `y_reset` at its default.',
         'On a rise of `inReset`, PI and PID set the integrator so the output before the limits is `yReset` (util.xeto:162-163). With P or PD, `inReset` does nothing.'] + PSEM,
    common=['stall'], ev=['util.xeto:155-242', 'haxall pull request #149', 'MBL 14 Reals/PIDWithReset.mo:46'])

# ---- stage, proof, variable pulse, assert
add('IntegersStage', 'nativeParams', 'hx.comps::Stage', {'u': 'in', 'y': 'out'},
    params={'n': {'slot': 'n', 'feed': 'set', 'convert': I2I}, 'holdDuration': {'slot': 'holdDuration', 'feed': 'set', 'convert': SEC},
            'h': {'slot': 'h', 'feed': 'set', 'convert': R2F}, 'pre_y_start': {'slot': 'initVal', 'feed': 'set', 'convert': I2I}},
    sem=['A null `h` is 0.02/n, the CDL default (stage.xeto:40).', 'It fires on the level of its condition, not its rise. At a hold of 0 MBL can stick and this comp does not (stage.xeto:26-29).',
         'The hold also runs from the first execute, as MBL. ASHRAE 231 7.5.71 starts it on the first change.',
         'CDL `holdDuration` and `n` have no default. The comp defaults them to 1min and 1 (stage.xeto:35, 38).'],
    common=['ownClock'], ev=['stage.xeto:9-48', 'haxall pull request #151'])
add('LogicalProof', 'nativeParams', 'hx.comps::Proof', {'u_s': 'inSet', 'u_m': 'inMeas', 'yLocFal': 'lockedFalse', 'yLocTru': 'lockedTrue'},
    params={'debounce': {'slot': 'debounce', 'feed': 'set', 'convert': SEC}, 'feedbackDelay': {'slot': 'feedbackDelay', 'feed': 'set', 'convert': SEC}},
    sem=['CDL `debounce` and `feedbackDelay` have no default. The comp defaults them to 10sec and 1min (proof.xeto:45, 48).',
         'A change of `inSet` away from a stable `inMeas` sets an output at once, so equipment that takes time to prove raises `lockedFalse` on each start, as MBL (proof.xeto:24-26).',
         'A change of `debounce` or `feedbackDelay` restarts the comp (proof.xeto:30-31).'],
    common=['ownClock', 'nullHold'], ev=['proof.xeto:9-55', 'haxall pull request #152'])
add('LogicalVariablePulse', 'nativeParams', 'hx.comps::VariablePulse', {'u': 'in', 'y': 'out'},
    params={'period': {'slot': 'period', 'feed': 'set', 'convert': SEC}, 'deltaU': {'slot': 'deltaU', 'feed': 'set', 'convert': R2F},
            'minTruFalHol': {'slot': 'minHold', 'feed': 'set', 'convert': SEC}},
    sem=['A null `minHold` is 0.01 times `period`, the CDL default (variablePulse.xeto:46).', 'The run period is the larger of `period` and 2.02 times `minHold` (variablePulse.xeto:10-11).',
         'CDL `period` has no default. The comp defaults it to 1min (variablePulse.xeto:41).'],
    common=['ownClock'], ev=['variablePulse.xeto:9-51', 'haxall pull request #152'])
add('UtilitiesAssert', 'nativeParams', 'hx.comps::Assert', {'u': 'in'}, params={'message': {'slot': 'message', 'feed': 'set'}}, unused=['out'],
    sem=['When `in` turns false the comp logs a warning to the `hxComps` log, at most hourly. It never throws or faults (assert.xeto:9-22).',
         'The comp has an `out` that CDL Assert lacks. It stays unlinked.',
         'An invalid `in` is not checked (assert.xeto:14-15).',
         'A binding may also grade this class compile-time, and a compiler may then drop it when `u` is a constant true.'],
    ev=['assert.xeto:9-32', 'Assert.fan', 'haxall pull request #151'])

# ---- psychrometrics
PSY = ['`inDryBulb` is in kelvin when unitless, and K, °C and °F convert. `inRelHumidity` is a fraction when unitless, and % converts (psychrometrics.xeto:10-12).',
       'An out of range or non-finite input gives NaN with no fault (psychrometrics.xeto:15-17).',
       'It computes with the 2025 ASHRAE Handbook and IAPWS-IF97, not the 2009 equations named in ASHRAE 231 7.5.54 and 7.5.55.']
add('PsychrometricsDewPoint_TDryBulPhi', 'native', 'hx.comps::DewPoint', {'TDryBul': 'inDryBulb', 'phi': 'inRelHumidity', 'TDewPoi': 'out'},
    sem=['Below the triple point `out` is the frost point over ice, where MBL gives a dew point over liquid water (psychrometrics.xeto:67-69).',
         'A dew point below 100 K gives NaN with fault (psychrometrics.xeto:61-62).', '`out` is in the unit of `inDryBulb` (psychrometrics.xeto:55-56).'] + PSY,
    ev=['psychrometrics.xeto:37-70', 'haxall pull request #150'])
add('PsychrometricsSpecificEnthalpy_TDryBulPhi', 'nativeParams', 'hx.comps::SpecificEnthalpy', {'TDryBul': 'inDryBulb', 'phi': 'inRelHumidity', 'h': 'out'},
    params={'pAtm': {'slot': 'pAtm', 'feed': 'set'}},
    sem=['Below 0 °C p_ws is over liquid water, where MBL takes it over ice. `out` is 247 J/kg higher at -5 °C and 80 % (psychrometrics.xeto:84-87).',
         '`out` carries `J/kg` only when `inDryBulb` has a unit (psychrometrics.xeto:80-82).'] + PSY,
    ev=['psychrometrics.xeto:37-43, 72-94', 'haxall pull request #150'])
add('PsychrometricsWetBulb_TDryBulPhi', 'native', 'hx.comps::WetBulb', {'TDryBul': 'inDryBulb', 'phi': 'inRelHumidity', 'TWetBul': 'out'},
    sem=['It uses the Stull (2011) approximation, valid for 5 % to 99 % and -20 °C to 50 °C within -1 K to +0.65 K (psychrometrics.xeto:96-100).',
         '`out` is in the unit of `inDryBulb` (psychrometrics.xeto:102-103).'] + PSY[:2],
    ev=['psychrometrics.xeto:37-43, 96-106', 'haxall pull request #150'])

# ---- line and limiter
add('RealsLimiter', 'nativeParams', 'hx.comps::Limiter', {'u': 'in', 'y': 'out'},
    params={'uMax': {'slot': 'uMax', 'feed': 'set'}, 'uMin': {'slot': 'uMin', 'feed': 'set'}},
    sem=['Equal limits give that value. MBL rejects them (math.xeto:165-167).', 'Limits convert to the unit of `in`, an offset included, so a °C limit fits a °F `in` (math.xeto:153-155).',
         '`uMax` and `uMin` have no default and `out` is NaN with fault until both are set (math.xeto:157-159).', 'By this table\'s rules it is nativeParams, not native, since two CDL parameters map to slots.'],
    ev=['math.xeto:151-179', 'haxall pull request #150'])
add('RealsLine', 'nativeParams', 'hx.comps::Line', {'u': 'in', 'x1': 'inX1', 'f1': 'inF1', 'x2': 'inX2', 'f2': 'inF2', 'y': 'out'},
    params={'limitBelow': {'slot': 'limitBelow', 'feed': 'set'}, 'limitAbove': {'slot': 'limitAbove', 'feed': 'set'}},
    sem=['An `inX2` not above `inX1` while a limit is on gives NaN with fault, where MBL warns (math.xeto:220-221).',
         'Each axis converts to the unit of its first input with a unit (math.xeto:206-210).'],
    ev=['math.xeto:203-243', 'haxall pull request #150'])

# ---- none
# ---- composites: classes no single comp runs, composed from classes that comps do run
# `compose` lists the instances, each (name, CDL class under CDL., bindings in the class's own parameters), and the
# connections in CDL names. generate.py writes each as a kw.cdl composite whose children are hx.comps comps.
add('LogicalNand', 'composite', 'kw.cdl::LogicalNand', compose={
        'insts': [('and1', 'Logical.And', {}), ('not1', 'Logical.Not', {})],
        'edges': [('u1', 'and1.u1'), ('u2', 'and1.u2'), ('and1.y', 'not1.u'), ('not1.y', 'y')]},
    composition='And {inA:u1, inB:u2} -> Not {in} -> y. Two comps.',
    reason='No single comp computes not(u1 and u2). It runs as And then Not.', ev=['logic.xeto:16-18, 38', 'MBL 14 Logical/Nand.mo'])
add('LogicalNor', 'composite', 'kw.cdl::LogicalNor', compose={
        'insts': [('or1', 'Logical.Or', {}), ('not1', 'Logical.Not', {})],
        'edges': [('u1', 'or1.u1'), ('u2', 'or1.u2'), ('or1.y', 'not1.u'), ('not1.y', 'y')]},
    composition='Or {inA:u1, inB:u2} -> Not {in} -> y. Two comps.',
    reason='No single comp computes not(u1 or u2). It runs as Or then Not.', ev=['logic.xeto:16-18, 41', 'MBL 14 Logical/Nor.mo'])
for n, conv, t, f in [('RealsSourcesPulse', 'Conversions.BooleanToReal', 'realTrue', 'realFalse'),
                      ('IntegersSourcesPulse', 'Conversions.BooleanToInteger', 'integerTrue', 'integerFalse')]:
    add(n, 'composite', 'kw.cdl::' + n, compose={
            'insts': [('pul', 'Logical.Sources.Pulse', {'width': 'width', 'period': 'period', 'shift': 'shift'}),
                      ('booTo', conv, {t: 'offset+amplitude', f: 'offset'})],
            'edges': [('pul.y', 'booTo.u'), ('booTo.y', 'y')]},
        composition='BoolPulse {width, period, shift} -> NumberSwitch.inSwitch, with NumberConst offset on inFalse and NumberConst offset+amplitude on inTrue.',
        reason='BoolPulse gives only the Boolean pulse. The comp doc prescribes a NumberSwitch for the Reals and Integers forms (pulse.xeto:18-21).',
        ev=['pulse.xeto:18-21', 'haxall pull request #151'])
# Logical.Pre is a `loopCut` link: the target reads the previous cycle's value of the source.
add('LogicalPre', 'link', None, {}, link={'from': 'u', 'to': 'y'}, requires={'loopCut': ['u']},
    dropped={'pre_u_start': 'A link carries no initial value, so the target reads null on the first cycle.'},
    departures=['The link reads null on the first cycle where MBL reads `pre_u_start` (Logical/Pre.mo). From the second cycle on it reads the previous cycle value of `u`, as MBL.'],
    sem=['A `loopCut` link delivers the previous cycle value at the end of the execute cycle (meta.xeto:10-16), in any order.'],
    ev=['meta.xeto:9-17', 'MBL 14 Logical/Pre.mo', 'meta.xeto:10-16 (a loopCut link reads the previous cycle value)'])
add('RealsSourcesCalendarTime', 'none', None, closest='hx.comps::CurTime (gives a DateTime)',
    reason='No comp outputs year, month, day, hour, minute and weekday as numbers. CurTime outputs one DateTime (timer.xeto:42-49).', ev=['timer.xeto:42-49', 'MBL 14 Reals/Sources/CalendarTime.mo'])
add('RealsSourcesCivilTime', 'none', None, closest='hx.comps::CurTime (gives a DateTime)',
    reason='No comp outputs time as seconds. CurTime outputs a DateTime and no conversion comp turns it into a Number (timer.xeto:42-49, conversions.xeto:11-72).', ev=['timer.xeto:42-49', 'conversions.xeto:11-72', 'MBL 14 Reals/Sources/CivilTime.mo'])
add('RealsSourcesRamp', 'none', None, closest='hx.comps::Ramp (a periodic waveform)',
    reason='CDL Ramp is one-shot: `offset` before `startTime`, then a rise of `height` over `duration`. hx.comps Ramp repeats over `period` from its own start (util.xeto:31-57, Ramp.fan startTicks).', ev=['util.xeto:31-57', 'Ramp.fan:38-66', 'MBL 14 Reals/Sources/Ramp.mo'])
add('RealsSourcesSin', 'none', None, closest='hx.comps::SineWave',
    reason='SineWave has no `phase` or `startTime`, measures `amplitude` peak to peak, takes a `period` of at least 1sec, and is phased from its own start (util.xeto:13-29, SineWave.fan startTicks).', ev=['util.xeto:13-29', 'SineWave.fan:36-54', 'MBL 14 Reals/Sources/Sin.mo'])
add('UtilitiesSunRiseSet', 'none', None, closest=None,
    reason='No comp computes sunrise or sunset times. A search of every hx.comps spec name finds none.', ev=['hx_comps_index.json, every spec name'])

# ---- arrays (28)
ARR = {
 'IntegersMultiSum': 'Reduction. Up to 4 inputs: hx.comps::Add, with a Multiply per input whose gain is not 1. Above 4: a tree.',
 'RealsMultiSum': 'Reduction. Up to 4 inputs: hx.comps::Add, with a Multiply per input whose gain is not 1. Above 4: a tree.',
 'RealsMultiMax': 'Reduction. Up to 4 inputs: hx.comps::Maximum. Above 4: a tree.',
 'RealsMultiMin': 'Reduction. Up to 4 inputs: hx.comps::Minimum. Above 4: a tree.',
 'LogicalMultiAnd': 'Reduction. Up to 4 inputs: hx.comps::And. Above 4: a tree. nin 0 has no inputs.',
 'LogicalMultiOr': 'Reduction. Up to 4 inputs: hx.comps::Or. Above 4: a tree. nin 0 has no inputs.',
 'RealsMatrixGain': 'Matrix. Multiply and Add trees over the constant matrix.',
 'RealsMatrixMax': 'Matrix. Maximum trees.', 'RealsMatrixMin': 'Matrix. Minimum trees.',
 'RealsSort': 'No comp yet. Vector in, vector and index vector out.',
 'RealsSourcesTimeTable': 'No comp yet. Table is constant, stepping needs a comp.',
 'IntegersSourcesTimeTable': 'No comp yet. Table is constant, stepping needs a comp.',
 'LogicalSourcesTimeTable': 'No comp yet. Table is constant, stepping needs a comp.',
}
for k in ['Real', 'Integer', 'Boolean']:
    ARR['Routing%sScalarReplicator' % k] = 'Routing. Links only.'
    ARR['Routing%sVectorReplicator' % k] = 'Routing. Links only.'
    ARR['Routing%sVectorFilter' % k] = 'Routing. Constant mask, links only.'
    ARR['Routing%sExtractSignal' % k] = 'Routing. Constant indices, links only.'
    ARR['Routing%sExtractor' % k] = 'Routing. Run-time index needs a select comp (%s, numInputs 3 to 10).' % ('hx.comps::BoolSelect' if k == 'Boolean' else 'hx.comps::NumberSelect')
for n, r in ARR.items():
    add(n, 'array', None, reason='Has a connector or parameter carrying `cdlArraySize`. It expands when a sequence is instantiated.', expansion=r,
        ev=['kw.cdl blocks.xeto (cdlArraySize)'])


# ---- unit rules: how each class carries units, for static unit propagation (units.py) ----
# family: A keeps one unit across the names in each `keep` group; B compares values of one unit, and its hysteresis
# or error scale is their difference (`op: delta`); C computes its output's unit from its inputs (`op`); D is math on
# dimensionless numbers; E carries Integers or counts; F carries Booleans and declared times; `array` is an array
# class, expanded when a sequence is instantiated. A declared cdlUnit seeds a name too, so a rule lists only what
# the declarations do not say. `u` in a rule of an array class stands for every element of the array `u`.
def R(family, keep=(), op=None, ins=(), out=None, seeds=None, note=""):
    return {"family": family, "keep": [list(k) for k in keep], "op": op, "ins": list(ins), "out": out,
            "seeds": dict(seeds or {}), "note": note}


UNIT_RULES = {}
for _n in ("RealsMin", "RealsMax", "RealsAverage", "RealsModulo"):
    UNIT_RULES[_n] = R("A", [["u1", "u2", "y"]])
UNIT_RULES["RealsSwitch"] = R("A", [["u1", "u3", "y"]])
for _n in ("RealsAbs", "DiscreteSampler", "DiscreteZeroOrderHold", "DiscreteFirstOrderHold", "DiscreteTriggeredMax",
           "DiscreteTriggeredMovingMean", "RealsMovingAverage", "RealsRound"):
    UNIT_RULES[_n] = R("A", [["u", "y"]])
UNIT_RULES["RealsAtan2"] = R("A", [["u1", "u2"]], seeds={"y": "1"}, note="the comp writes an unitless angle")
for _n in ("DiscreteUnitDelay", "DiscreteTriggeredSampler"):
    UNIT_RULES[_n] = R("A", [["u", "y", "y_start"]])
UNIT_RULES["RealsLine"] = R("A", [["f1", "f2", "y"], ["u", "x1", "x2"]])
UNIT_RULES["RealsLimiter"] = R("A", [["u", "uMin", "uMax", "y"]])
UNIT_RULES["RealsHysteresis"] = R("A", [["u", "uLow", "uHigh"]])
UNIT_RULES["RealsSourcesConstant"] = R("A", [["k", "y"]], note="the constant's y is its k")
UNIT_RULES["ConversionsBooleanToReal"] = R("A", [["realTrue", "realFalse", "y"]])
UNIT_RULES["RealsSourcesPulse"] = R("C", op="add", ins=["offset", "amplitude"], out="y",
                                    note="y is offset while off and offset plus amplitude while on, so amplitude is "
                                         "a difference beside an absolute offset")
for _n in ("RealsLimitSlewRate", "RealsRamp"):
    UNIT_RULES[_n] = R("A", [["u", "y"]], note="a slew rate is the unit of u per second, a compound with no symbol")
UNIT_RULES["RealsIntegratorWithReset"] = R("A", [["y", "y_reset_in", "y_start"]],
                                            note="y is k times the integral of u, a compound unit")
for _n in ("PsychrometricsDewPoint_TDryBulPhi", "PsychrometricsWetBulb_TDryBulPhi"):
    UNIT_RULES[_n] = R("A", [["TDryBul", _n.startswith("PsychrometricsDewPoint") and "TDewPoi" or "TWetBul"]])
UNIT_RULES["PsychrometricsSpecificEnthalpy_TDryBulPhi"] = R("D", note="every connector and pAtm declare their unit")
for _n in ("RealsGreaterThreshold", "RealsLessThreshold"):
    UNIT_RULES[_n] = R("B", [["u", "t"]], "delta", ["u"], "h")
for _n in ("RealsGreater", "RealsLess"):
    UNIT_RULES[_n] = R("B", [["u1", "u2"]], "delta", ["u1"], "h")
_PID_SEEDS = {"y": "1", "yMax": "1", "yMin": "1", "xi_start": "1", "yd_start": "1"}
UNIT_RULES["RealsPid"] = R("B", [["u_s", "u_m"]], "delta", ["u_s"], "r", _PID_SEEDS,
                           note="r scales the control error, so it is a difference in the unit of u_s")
UNIT_RULES["RealsPidWithReset"] = R("B", [["u_s", "u_m"]], "delta", ["u_s"], "r", dict(_PID_SEEDS, y_reset="1"),
                                    note="r scales the control error, so it is a difference in the unit of u_s")
UNIT_RULES["RealsAdd"] = R("C", op="add", ins=["u1", "u2"], out="y")
UNIT_RULES["RealsAddParameter"] = R("C", op="add", ins=["u", "p"], out="y")
UNIT_RULES["RealsSubtract"] = R("C", op="sub", ins=["u1", "u2"], out="y")
UNIT_RULES["RealsMultiply"] = R("C", op="mul", ins=["u1", "u2"], out="y")
UNIT_RULES["RealsMultiplyByParameter"] = R("C", op="mul", ins=["u", "k"], out="y")
UNIT_RULES["RealsDivide"] = R("C", op="div", ins=["u1", "u2"], out="y")
for _n in ("RealsAcos", "RealsAsin", "RealsAtan", "RealsCos", "RealsSin", "RealsTan", "RealsExp", "RealsLog",
           "RealsLog10", "RealsSqrt"):
    UNIT_RULES[_n] = R("D", note="math on dimensionless numbers; the comp ignores the input unit")
UNIT_RULES["RealsDerivative"] = R("D", note="y is k times the derivative of u, a compound unit")
UNIT_RULES["ConversionsIntegerToReal"] = R("E", seeds={"y": "1"}, note="a count is dimensionless")
for _n in ("ConversionsBooleanToInteger", "ConversionsRealToInteger", "IntegersAbs", "IntegersAdd",
           "IntegersAddParameter", "IntegersChange", "IntegersEqual", "IntegersGreater", "IntegersGreaterEqual",
           "IntegersGreaterEqualThreshold", "IntegersGreaterThreshold", "IntegersLess", "IntegersLessEqual",
           "IntegersLessEqualThreshold", "IntegersLessThreshold", "IntegersMax", "IntegersMin", "IntegersMultiply",
           "IntegersOnCounter", "IntegersSourcesConstant", "IntegersSourcesPulse", "IntegersStage",
           "IntegersSubtract", "IntegersSwitch"):
    UNIT_RULES[_n] = R("E", note="Integers carry no unit")
for _n in ("LogicalAnd", "LogicalChange", "LogicalEdge", "LogicalFallingEdge", "LogicalLatch", "LogicalNand",
           "LogicalNor", "LogicalNot", "LogicalOr", "LogicalPre", "LogicalProof", "LogicalSourcesConstant",
           "LogicalSourcesPulse", "LogicalSourcesSampleTrigger", "LogicalSwitch", "LogicalTimer",
           "LogicalTimerAccumulating", "LogicalToggle", "LogicalTrueDelay", "LogicalTrueFalseHold",
           "LogicalVariablePulse", "LogicalXor", "UtilitiesAssert"):
    UNIT_RULES[_n] = R("F", note="Booleans; a time parameter declares its unit")
for _n in ("RealsMultiMax", "RealsMultiMin", "RoutingRealScalarReplicator", "RoutingRealVectorReplicator",
           "RoutingRealVectorFilter", "RoutingRealExtractSignal", "RoutingRealExtractor"):
    UNIT_RULES[_n] = R("array", [["u", "y"]])
UNIT_RULES["RealsMultiSum"] = R("array", op="sum", ins=["u"], out="y",
                                note="a weighted sum of absolute temperatures gives no unit until its weights are known")
for _n in ("IntegersMultiSum", "LogicalMultiAnd", "LogicalMultiOr", "RoutingBooleanExtractSignal",
           "RoutingBooleanExtractor", "RoutingBooleanScalarReplicator", "RoutingBooleanVectorFilter",
           "RoutingBooleanVectorReplicator", "RoutingIntegerExtractSignal", "RoutingIntegerExtractor",
           "RoutingIntegerScalarReplicator", "RoutingIntegerVectorFilter", "RoutingIntegerVectorReplicator",
           "IntegersSourcesTimeTable", "LogicalSourcesTimeTable"):
    UNIT_RULES[_n] = R("array", note="Integers or Booleans")
for _n in ("RealsMatrixGain", "RealsMatrixMax", "RealsMatrixMin", "RealsSort", "RealsSourcesTimeTable"):
    UNIT_RULES[_n] = R("array", note="expanded when instantiated; its units follow the expansion")
for _n, _r in UNIT_RULES.items():
    if _n in T:
        T[_n]["unitRule"] = _r
