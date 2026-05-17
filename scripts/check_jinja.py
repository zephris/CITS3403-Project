from pathlib import Path
import re
p=Path('templates/index.html')
s=p.read_text(encoding='utf-8')
lines=s.splitlines()
stack=[]
pattern_if=re.compile(r"\{%\s*if\b")
pattern_endif=re.compile(r"\{%\s*endif\s*%\}")
for i,l in enumerate(lines, start=1):
    if pattern_if.search(l):
        stack.append((i,l.strip()))
    if pattern_endif.search(l):
        if stack:
            stack.pop()
        else:
            print(f"Unmatched endif at line {i}: {l.strip()}")
print('Total ifs:', sum(1 for _ in pattern_if.finditer(s)))
print('Total endifs:', len(re.findall(r"\{%\s*endif\s*%\}", s)))
if stack:
    print('Unclosed ifs:')
    for ln,txt in stack:
        print(ln, txt)
else:
    print('No unclosed if blocks found.')
