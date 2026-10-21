"""A JavaScript lexer, in pure Python, for the web UI's syntax gate.

WHAT THIS IS: a LEXER, not a parser. It reads a file the way a JavaScript
engine's scanner reads it -- comments, string literals, template literals with
their `${}` holes, and regular-expression literals -- and it reports the
things that make a file unparseable at the LEXICAL level:

  * a string, template literal, comment or regex that is never terminated
  * a bracket that is never closed, closed twice, or closed by the wrong kind
  * a `${}` hole that is never closed

WHAT THIS IS NOT: a parser. It cannot tell that `const x = ;` is nonsense --
only an engine can, because only an engine builds the grammar. The node engine
in `tools/check_js_syntax.py` is the authoritative check; this module is the
fallback for a machine with no node, and it is deliberately loud about what it
does and does not cover.

WHY A LEXER IS THE RIGHT SHAPE FOR THIS TREE. The web UI is made of files
like `templates_settings.js`, whose payload is HTML held inside a template
literal. The browser parses the FILE as one classic script; the HTML inside
the backticks is opaque to the parser, and only the `${...}` holes are
JavaScript. So the unit of checking is the file, and the payload is not
code. A checker that pulled the HTML out and judged it as code would be
judging the wrong thing -- and the historical failure was exactly a payload
mistake: a stray backtick inside a template literal ended the literal early,
and everything after it was read as JavaScript.

THE REGEX/DIVISION AMBIGUITY. A `/` starts a regular expression or is a
division operator depending on what came before it, and only a parser can
always say which. The rule used here is the conventional one: a `/` starts a
regex where an EXPRESSION may start (after an operator, an opening bracket, a
comma, a semicolon, or one of the keywords that take an expression) and is a
division everywhere else. That is how every hand-written scanner does it, and
it is why this module validates against the whole real tree: a rule that
mis-reads a real file reports a finding on a file that is fine, which is the
one failure mode a gate must never have.
"""
from __future__ import annotations

from dataclasses import dataclass

# Keywords after which a `/` starts a regular expression rather than dividing.
# `this`, `true`, `false` and `null` are VALUES, so they are not here: after
# them a `/` divides.
_REGEX_KEYWORDS = frozenset({
    "await", "case", "delete", "do", "else", "in", "instanceof", "new", "of",
    "return", "throw", "typeof", "void", "yield",
})

# Characters after which a `/` divides rather than starting a regex.
_VALUE_ENDERS = frozenset(")]}")

_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {")": "(", "]": "[", "}": "{"}


@dataclass(frozen=True)
class Problem:
    """One lexical defect, with where it was found."""

    line: int
    column: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}, column {self.column}: {self.message}"


class _Frame:
    """One level of the scanner: either code, or the raw text of a template.

    `code` frames carry the bracket stack and the last significant token (the
    "can a regex start here" state). `raw` frames carry the position of the
    backtick that opened them, so an unterminated template can say where it
    started.
    """

    def __init__(self, kind: str, line: int = 0, column: int = 0) -> None:
        self.kind = kind
        self.line = line
        self.column = column
        self.brackets: list[tuple[str, int, int]] = []
        self.prev = ""


def scan(source: str) -> list[Problem]:
    """Lex `source` and return every lexical defect found.

    An empty list means the file is lexically well formed. It does NOT mean
    the file is valid JavaScript -- only an engine can say that.
    """
    problems: list[Problem] = []
    frames = [_Frame("code")]
    i = 0
    n = len(source)
    line = 1
    column = 1

    def advance(count: int = 1) -> None:
        nonlocal i, line, column
        for _ in range(count):
            if i < n and source[i] == "\n":
                line += 1
                column = 1
            else:
                column += 1
            i += 1

    def regex_allowed(frame: _Frame) -> bool:
        prev = frame.prev
        if prev == "":
            return True
        return prev not in _VALUE_ENDERS and prev != "value"

    while i < n:
        frame = frames[-1]
        ch = source[i]

        if frame.kind == "raw":
            # The payload of a template literal: opaque to the parser except
            # for the `${}` holes.
            if ch == "\\":
                advance(2)
                continue
            if ch == "`":
                frames.pop()
                frames[-1].prev = "value"
                advance()
                continue
            if ch == "$" and i + 1 < n and source[i + 1] == "{":
                frames.append(_Frame("code"))
                advance(2)
                continue
            advance()
            continue

        # --- code -----------------------------------------------------------
        if ch in " \t\r\n\f\v ﻿":
            advance()
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                advance()
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            start_line, start_column = line, column
            advance(2)
            closed = False
            while i < n:
                if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                    advance(2)
                    closed = True
                    break
                advance()
            if not closed:
                problems.append(Problem(start_line, start_column,
                                        "block comment is never closed"))
            continue
        if ch == "/" and regex_allowed(frame):
            start_line, start_column = line, column
            advance()
            closed = False
            in_class = False
            while i < n:
                c = source[i]
                if c == "\\":
                    advance(2)
                    continue
                if c == "\n":
                    break
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    advance()
                    closed = True
                    break
                advance()
            if not closed:
                problems.append(Problem(start_line, start_column,
                                        "regular expression is never closed"))
                frame.prev = "value"
                continue
            while i < n and (source[i].isalpha()):
                advance()
            frame.prev = "value"
            continue
        if ch in "\"'":
            start_line, start_column = line, column
            quote = ch
            advance()
            closed = False
            while i < n:
                c = source[i]
                if c == "\\":
                    advance(2)
                    continue
                if c == quote:
                    advance()
                    closed = True
                    break
                if c == "\n":
                    break
                advance()
            if not closed:
                problems.append(Problem(start_line, start_column,
                                        "string literal is never closed"))
            frame.prev = "value"
            continue
        if ch == "`":
            frames.append(_Frame("raw", line, column))
            advance()
            continue
        if ch in _OPENERS:
            frame.brackets.append((ch, line, column))
            frame.prev = "op"
            advance()
            continue
        if ch in _CLOSERS:
            if frame.brackets:
                opener, open_line, open_column = frame.brackets.pop()
                if _OPENERS[opener] != ch:
                    problems.append(Problem(
                        line, column,
                        f"`{ch}` closes `{opener}` opened on line {open_line}"))
            elif ch == "}" and len(frames) > 1:
                # The end of a `${}` hole: the code frame belongs to the
                # template below it, so this `}` closes the hole.
                frames.pop()
                frames[-1].prev = "value"
                advance()
                continue
            else:
                problems.append(Problem(line, column,
                                        f"`{ch}` has no matching opener"))
            frame.prev = "value"
            advance()
            continue
        if ch.isalpha() or ch in "_$":
            start = i
            while i < n and (source[i].isalnum() or source[i] in "_$"):
                advance()
            word = source[start:i]
            frame.prev = "op" if word in _REGEX_KEYWORDS else "value"
            continue
        if ch.isdigit():
            while i < n and (source[i].isalnum() or source[i] == "."):
                advance()
            frame.prev = "value"
            continue
        frame.prev = "op"
        advance()

    # --- what is left over -------------------------------------------------
    while frames:
        frame = frames.pop()
        if frame.kind == "raw":
            problems.append(Problem(frame.line, frame.column,
                                    "template literal is never closed"))
            continue
        for opener, open_line, open_column in frame.brackets:
            problems.append(Problem(open_line, open_column,
                                    f"`{opener}` is never closed"))
    return problems
