"""MATLAB tokenizer (FE-1).

Handles numbers, identifiers, operators (including the dotted forms),
comments (`%` to end of line), line continuations (`...`), strings, and the
transpose-vs-string ambiguity of `'`.
"""

from __future__ import annotations

from typing import NamedTuple


class Tok(NamedTuple):
    kind: str  # NUM | ID | OP | STR | NEWLINE | EOF
    text: str
    line: int
    col: int
    pos: int  # character offset into the source (FE-4 spans)


class MatlabSyntaxError(Exception):
    """A statement-level parse problem; callers record it and continue (FE-3)."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


TWO_CHAR_OPS = (".*", "./", ".\\", ".^", ".'", "==", "~=", "<=", ">=", "&&", "||")
ONE_CHAR_OPS = "+-*/\\^'()[]{},;:<>=&|~@"


def tokenize(text: str) -> list[Tok]:
    """Tokenize MATLAB source; raises MatlabSyntaxError on lexical errors."""
    toks: list[Tok] = []
    i = 0
    line = 1
    col = 1
    n = len(text)

    def prev_significant() -> Tok | None:
        return toks[-1] if toks and toks[-1].kind != "NEWLINE" else None

    while i < n:
        ch = text[i]
        if ch == "\n":
            toks.append(Tok("NEWLINE", "\n", line, col, i))
            i += 1
            line += 1
            col = 1
            continue
        if ch in " \t\r":
            i += 1
            col += 1
            continue
        if ch == "%":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("...", i):
            while i < n and text[i] != "\n":
                i += 1
            if i < n:  # swallow the newline: continuation
                i += 1
                line += 1
                col = 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            toks.append(Tok("NUM", text[i:j], line, col, i))
            col += j - i
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            toks.append(Tok("ID", text[i:j], line, col, i))
            col += j - i
            i = j
            continue
        two = text[i : i + 2]
        if two in TWO_CHAR_OPS:
            toks.append(Tok("OP", two, line, col, i))
            i += 2
            col += 2
            continue
        if ch == "'":
            prev = prev_significant()
            if prev is not None and (
                prev.kind in ("ID", "NUM") or (prev.kind == "OP" and prev.text in (")", "]", "'"))
            ):
                toks.append(Tok("OP", "'", line, col, i))
                i += 1
                col += 1
                continue
            j = i + 1
            while j < n and text[j] != "\n":
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= n or text[j] != "'":
                raise MatlabSyntaxError("unterminated string literal", line)
            toks.append(Tok("STR", text[i : j + 1], line, col, i))
            col += j + 1 - i
            i = j + 1
            continue
        if ch in ONE_CHAR_OPS:
            toks.append(Tok("OP", ch, line, col, i))
            i += 1
            col += 1
            continue
        raise MatlabSyntaxError(f"unexpected character {ch!r}", line)
    toks.append(Tok("EOF", "", line, col, i))
    return toks
