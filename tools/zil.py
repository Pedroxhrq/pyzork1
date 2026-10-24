"""Reader for the ZIL notation used by the archived Zork I sources."""

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Atom:
    name: str


@dataclass(frozen=True)
class Form:
    items: tuple


@dataclass(frozen=True)
class Prefix:
    kind: str
    value: object


class Reader:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def read(self):
        text = self.text
        while self.pos < len(text):
            c = text[self.pos]
            if c.isspace():
                self.pos += 1
                continue
            if c == ';':
                self.pos += 1
                self.read()
                continue
            break
        if self.pos == len(text):
            raise EOFError
        c = text[self.pos]
        self.pos += 1
        if c in '<(':
            end = '>' if c == '<' else ')'
            items = []
            while True:
                while self.pos < len(text) and text[self.pos].isspace():
                    self.pos += 1
                if self.pos >= len(text):
                    raise ValueError('Unterminated form')
                if text[self.pos] == ';':
                    self.pos += 1
                    self.read()
                    continue
                if text[self.pos] == end:
                    self.pos += 1
                    return Form(tuple(items)) if c == '<' else tuple(items)
                items.append(self.read())
        if c == '"':
            value = []
            while self.pos < len(text):
                c = text[self.pos]
                self.pos += 1
                if c == '"':
                    # ZIL folds physical line breaks, but | is a printed newline.
                    return re.sub(r'\s*\n\s*', ' ', ''.join(value)).replace('| ', '\n').replace('|', '\n')
                if c == '\\':
                    c = text[self.pos]
                    self.pos += 1
                value.append(c)
            raise ValueError('Unterminated string')
        if c in ",.'%":
            return Prefix(c, self.read())
        if c == '#':
            start = self.pos
            while self.pos < len(text) and not text[self.pos].isspace():
                self.pos += 1
            return Prefix('#' + text[start:self.pos], self.read())
        value = []
        while True:
            if c == '\\' and self.pos < len(text):
                c = text[self.pos]
                self.pos += 1
            value.append(c)
            if self.pos == len(text) or text[self.pos].isspace() or text[self.pos] in '<>();",':
                break
            c = text[self.pos]
            self.pos += 1
        name = ''.join(value)
        if re.fullmatch(r'-?\d+', name):
            return int(name)
        return Atom(name)


def read_file(path: Path):
    reader = Reader(path.read_text(encoding='utf-8'))
    forms = []
    while True:
        try:
            forms.append(reader.read())
        except EOFError:
            return forms


def name(value):
    return value.name if isinstance(value, Atom) else ''


def head(value):
    return name(value.items[0]) if isinstance(value, Form) and value.items else ''


def walk(value):
    yield value
    if isinstance(value, Prefix):
        yield from walk(value.value)
    elif isinstance(value, (Form, tuple)):
        for item in value.items if isinstance(value, Form) else value:
            yield from walk(item)


SOURCES = ('gmacros', 'gsyntax', '1dungeon', 'gglobals', 'gclock',
           'gmain', 'gparser', 'gverbs', '1actions')


def compile_time(value):
    if isinstance(value, Prefix):
        if value.kind in (',', "'"):
            return compile_time(value.value)
    if isinstance(value, Atom):
        return {'T': 1, 'ELSE': 1, 'ZORK-NUMBER': 1, 'PREDGEN': 1}.get(value.name, 0)
    if isinstance(value, Form):
        if not value.items:
            return 0
        op, *args = value.items
        if name(op) in ('==?', 'EQUAL?'):
            return compile_time(args[0]) == compile_time(args[1])
        if name(op) == 'GASSIGNED?':
            return name(args[0]) == 'PREDGEN'
        if name(op) == 'N==?':
            return compile_time(args[0]) != compile_time(args[1])
        if name(op) == 'OR':
            return any(compile_time(x) for x in args)
        if name(op) == 'AND':
            return all(compile_time(x) for x in args)
        if name(op) == 'NOT':
            return not compile_time(args[0])
        if name(op) == 'COND':
            for clause in args:
                if compile_time(clause[0]):
                    return clause[-1] if len(clause) > 1 else 1
            return Form(())
        if not value.items:
            return 0
        raise ValueError(f'Unsupported compile-time form {value}')
    return value


def preprocess(value):
    if isinstance(value, Prefix):
        if value.kind == '%':
            result = compile_time(value.value)
            if isinstance(result, Prefix) and result.kind == "'":
                result = result.value
            return preprocess(result)
        return Prefix(value.kind, preprocess(value.value))
    if isinstance(value, Form):
        return Form(tuple(preprocess(x) for x in value.items))
    if isinstance(value, tuple):
        return tuple(preprocess(x) for x in value)
    return value


def source_forms(root: Path):
    for source in SOURCES:
        for value in read_file(root / f'{source}.zil'):
            value = preprocess(value)
            if head(value) == 'COND':
                for clause in value.items[1:]:
                    if compile_time(clause[0]):
                        for child in clause[1:]:
                            yield source, child
                        break
            elif isinstance(value, Form):
                yield source, value


if __name__ == '__main__':
    from collections import Counter
    forms = list(source_forms(Path(__file__).resolve().parents[2] / 'historical'))
    print('Declarations:', Counter(head(f) for _, f in forms))
    routines = {name(f.items[1]) for _, f in forms if head(f) == 'ROUTINE'}
    ops = Counter(head(x) for _, f in forms if head(f) == 'ROUTINE'
                  for x in walk(f) if isinstance(x, Form))
    print('Primitives:', {k: v for k, v in ops.items() if k not in routines})
