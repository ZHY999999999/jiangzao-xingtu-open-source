#!/usr/bin/env python3
"""Static checks for the design-token contract in src/styles; no build or data needed.

python scripts/test_styles.py

1. Font sizes come from the scale in tokens.css. A literal px size is only allowed
   above 42px (display sizes) or inside clamp(); nothing may fall below --fs-xs (11px).
2. Every var(--name) used in styles or components is defined somewhere.
3. Palette colours live in tokens.css only. A rule may keep a literal colour when the
   line carries an `allow-color` comment explaining why (e.g. a fixed chart series).
"""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
STYLES = APP / 'src' / 'styles'
TOKENS = STYLES / 'tokens.css'
SRC = APP / 'src'
MIN_PX = 11
DISPLAY_PX = 42  # literals above this are hero/display sizes and stay fluid or explicit

FONT_SIZE = re.compile(r'font-size:\s*(\d+(?:\.\d+)?)px')
FONT_SHORTHAND = re.compile(r'font:\s*(?:[1-9]00\s+)?(\d+(?:\.\d+)?)px')
INLINE_FONT_SIZE = re.compile(r'fontSize:\s*[\'"]?(\d+(?:\.\d+)?)')
VAR_USE = re.compile(r'var\((--[A-Za-z0-9_-]+)')
VAR_DEF = re.compile(r'(--[A-Za-z0-9_-]+)\s*:')
VAR_SET = re.compile(r'setProperty\(\s*[\'"](--[A-Za-z0-9_-]+)[\'"]')
HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')


def lines(path):
    return path.read_text(encoding='utf-8').splitlines()


def check_font_sizes(problems):
    for path in sorted(STYLES.glob('*.css')):
        if path == TOKENS:
            continue
        for number, line in enumerate(lines(path), 1):
            for pattern in (FONT_SIZE, FONT_SHORTHAND):
                for match in pattern.finditer(line):
                    px = float(match.group(1))
                    if px <= DISPLAY_PX:
                        problems.append(f'{path.name}:{number}: literal {px:g}px must use a --fs-* token (floor {MIN_PX}px, display sizes > {DISPLAY_PX}px)')
    for path in sorted(SRC.rglob('*.tsx')):
        for number, line in enumerate(lines(path), 1):
            for match in INLINE_FONT_SIZE.finditer(line):
                if float(match.group(1)) < MIN_PX:
                    problems.append(f'{path.relative_to(APP)}:{number}: inline fontSize {match.group(1)} below {MIN_PX}px')


def check_variables(problems):
    defined, used = set(), {}
    sources = list(STYLES.glob('*.css')) + list(SRC.rglob('*.tsx')) + list(SRC.rglob('*.ts')) + list(SRC.rglob('*.js'))
    for path in sources:
        text = path.read_text(encoding='utf-8')
        if path.suffix == '.css':
            defined |= set(VAR_DEF.findall(text))
        defined |= set(VAR_SET.findall(text))
        for name in VAR_USE.findall(text):
            used.setdefault(name, set()).add(path.name)
    for name in sorted(used):
        if name not in defined:
            problems.append(f'{name} is used in {", ".join(sorted(used[name]))} but never defined')


def check_colours(problems):
    for path in sorted(STYLES.glob('*.css')):
        if path == TOKENS:
            continue
        for number, line in enumerate(lines(path), 1):
            if 'allow-color' in line or 'mask-image' in line or '-webkit-mask' in line:
                continue
            found = HEX.findall(line)
            if found:
                problems.append(f'{path.name}:{number}: literal colour {", ".join(found)}; use a token from tokens.css or mark the line allow-color with a reason')


def main():
    if not TOKENS.exists():
        print('tokens.css is missing; the style contract has no source of truth')
        return 1
    problems = []
    check_font_sizes(problems)
    check_variables(problems)
    check_colours(problems)
    for problem in problems:
        print(problem)
    print(f'{"FAIL" if problems else "PASS"} style contract: {len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
