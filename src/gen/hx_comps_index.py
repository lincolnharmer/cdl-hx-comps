#!/usr/bin/env python3
#
# Copyright (c) 2026, kW Engineering
# Licensed under the Academic Free License version 3.0
#
"""Index the hx.comps Xeto source: every spec with its file, line, base and slots, its base's slots included.

  python -X utf8 src/gen/hx_comps_index.py <hx.comps source dir> src/gen/hx_comps_index.json

classmap.py checks the class-to-comp table against the index. The committed index was written from src/xeto/hx.comps
of a haxall tree carrying haxall pull requests #138 to #152. test_classmap.py rewrites it from that source when
HX_COMPS_SRC names the directory, and compares.
"""
import json
import os
import re
import sys


def index(d):
    specs = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.xeto'):
            continue
        cur = None; depth = 0; incomment = False
        for i, line in enumerate(open(os.path.join(d, fn), encoding='utf-8'), 1):
            s = line.rstrip('\n')
            if s.strip().startswith('/*'):
                incomment = True
            if incomment:
                if '*/' in s:
                    incomment = False
                continue
            code = re.sub(r'//.*', '', s)
            if depth == 0:
                m = re.match(r'^(\w+):\s*([\w.:]+)', code)
                if m and not code.startswith('@'):
                    cur = {'name': m.group(1), 'base': m.group(2), 'file': fn, 'line': i, 'slots': {}}
                    specs[m.group(1)] = cur
                    inl = re.search(r'\{(.*)\}', code)
                    if inl:
                        for sm in re.finditer(r'(\w+):\s*([\w:?]+)', inl.group(1)):
                            cur['slots'][sm.group(1)] = {'type': sm.group(2), 'line': i, 'raw': inl.group(1).strip()}
                    elif code.rstrip().endswith('{'):
                        depth = 1
                    continue
            else:
                depth += code.count('{') - code.count('}')
                if depth <= 0:
                    depth = 0
                    continue
                m = re.match(r'^\s{2}(\w+):\s*([\w:?]+)(.*)$', code)
                if m and depth == 1:
                    cur['slots'][m.group(1)] = {'type': m.group(2), 'line': i, 'raw': code.strip()}
                elif depth == 1 and cur['base'] == 'Enum':
                    item = re.match(r'^\s{2}([a-z]\w*)\s*(<.*>)?\s*$', code)
                    if item:
                        cur.setdefault('items', []).append(item.group(1))

    def resolved(name):
        sp = specs[name]; out = {}
        if sp['base'] in specs:
            out.update(resolved(sp['base']))
        for k, v in sp['slots'].items():
            out[k] = dict(v, file=sp['file'])
        return out
    out = {}
    for n in specs:
        out[n] = {'file': specs[n]['file'], 'line': specs[n]['line'], 'base': specs[n]['base'], 'slots': resolved(n)}
        if 'items' in specs[n]:
            out[n]['items'] = specs[n]['items']
    return out


def render(res):
    return json.dumps(res, indent=1)


if __name__ == "__main__":
    res = index(sys.argv[1])
    with open(sys.argv[2], 'w', encoding='utf-8', newline='\n') as f:
        f.write(render(res))
    print(len(res), 'specs')
