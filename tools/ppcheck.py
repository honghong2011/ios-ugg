import re, sys

def strip(src):
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)
    src = re.sub(r'"(\\.|[^"\\])*"', '""', src)
    src = re.sub(r"'(\\.|[^'\\])*'", "''", src)
    return src

def branch(lines, ugg):
    """Keep only the lines of each #if branch that the build would take."""
    out = []
    stack = []          # each: (parent_active, this_active)
    for l in lines:
        m = re.match(r'\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)', l)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            parent = all(a for _, a in stack)
            if kind in ('if', 'ifdef', 'ifndef'):
                if kind == 'if':
                    neg = rest.startswith('!')
                    e = rest.lstrip('!').strip()
                    mm = re.match(r'defined\s*\(\s*(\w+)\s*\)', e)
                    if mm:
                        val = (mm.group(1) == 'UGG_BOARD') if ugg else (mm.group(1) != 'UGG_BOARD')
                        # for ugg=False we do not know other macros: treat as off
                        val = (mm.group(1) == 'UGG_BOARD') and ugg
                    else:
                        val = False
                    if neg:
                        val = not val
                elif kind == 'ifdef':
                    val = (rest.split()[0] == 'UGG_BOARD') and ugg
                else:
                    val = not ((rest.split()[0] == 'UGG_BOARD') and ugg)
                stack.append((parent, val))
            elif kind in ('elif', 'else'):
                if stack:
                    p, v = stack[-1]
                    stack[-1] = (p, not v)
            elif kind == 'endif':
                if stack:
                    stack.pop()
            continue
        if all(a for _, a in stack):
            out.append(l)
    return out

p = sys.argv[1]
lines = open(p, encoding='utf-8', errors='replace').read().split('\n')
for ugg in (True, False):
    body = strip('\n'.join(branch(lines, ugg)))
    print("%-12s braces=%+d parens=%+d brackets=%+d" %
          ("UGG_BOARD=1" if ugg else "UGG_BOARD=0",
           body.count('{') - body.count('}'),
           body.count('(') - body.count(')'),
           body.count('[') - body.count(']')))
