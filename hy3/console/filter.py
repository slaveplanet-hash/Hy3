"""Wireshark-style display-filter for the operator console event list (plan §6/§16).

The console event list is a flat, sortable, filterable table in the spirit of
Wireshark's packet list. Operators type a display-filter expression and the list
narrows. The grammar is intentionally small and safe:

    kind:cap.call              equality on a column
    kind:cap.call,cap.result   IN list (comma-separated)
    risk:write
    !kind:cap.error            negation (also written ``kind!=cap.error``)
    capability:net.scan        column equality (alias ``cap``)
    provider:lm-studio
    session:<id>   job:<id>
    entity:192.168.1.180       payload substring match (also via mentions when present)
    text:"dns query"           payload substring match (aliases ``body``)
    192.168.1.180              free term -> payload substring match (AND-ed)

Values may be double- or single-quoted to preserve internal spaces. The parser is
pure and the compiler emits parameterized SQL only (no string interpolation of
user values), so it is injection-safe by construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# Keys that map directly onto columns of the ``events`` table.
_COLUMN_KEYS = {
    "kind": "kind",
    "risk": "risk",
    "capability": "capability_id",
    "cap": "capability_id",
    "provider": "provider",
    "session": "session_id",
    "job": "job_id",
}
# Keys matched against the JSON payload (substring / LIKE).
_TEXT_KEYS = {"text", "body", "entity"}
_VALID_KEYS = set(_COLUMN_KEYS) | _TEXT_KEYS


@dataclass
class Clause:
    """One ``key:value`` (or negated) filter clause."""

    key: str
    value: str
    negate: bool = False


@dataclass
class ParsedFilter:
    """Result of parsing a display-filter expression."""

    clauses: List[Clause] = field(default_factory=list)
    free: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.clauses and not self.free


def _tokenize(text: str) -> List[str]:
    """Split on spaces while keeping quoted values intact.

    A token is a maximal run of non-space characters, except that characters
    inside matching double/single quotes are never split.
    """
    tokens: List[str] = []
    cur: List[str] = []
    in_quote: str | None = None
    for ch in text:
        if in_quote is not None:
            cur.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            cur.append(ch)
            continue
        if ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def _unquote(value: str) -> str:
    """Strip a single layer of matching quotes from a value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_filter(query: str) -> ParsedFilter:
    """Parse a display-filter expression into clauses + free terms + errors."""
    pf = ParsedFilter()
    if not query or not query.strip():
        return pf
    for tok in _tokenize(query):
        # Forms:  !key:value   key:value   key!=value
        # The separator is a bare ':' or the '!=' operator; a leading '!' negates.
        m = re.match(r"^(!?)([a-zA-Z_]+)(:|!=)(.*)$", tok)
        if not m:
            pf.free.append(tok)
            continue
        negate = tok.startswith("!") or m.group(3) == "!="
        key = m.group(2)
        value = _unquote(m.group(4))
        if key not in _VALID_KEYS:
            pf.errors.append(f"unknown filter key: {key!r} (known: {', '.join(sorted(_VALID_KEYS))})")
            continue
        pf.clauses.append(Clause(key=key, value=value, negate=negate))
    return pf


def _like_pattern(term: str) -> str:
    """Escape LIKE wildcards in ``term`` and wrap with % sentinels.

    We ESCAPE with backslash so a user's ``%``/``_`` are treated literally rather
    than as SQL wildcards.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def compile_event_filter(
    query: str, *, session_id: str | None = None
) -> Tuple[str, List[str], List[str]]:
    """Compile a display-filter into a parameterized ``WHERE`` clause.

    Returns ``(where_sql, params, errors)``. ``where_sql`` is safe to splice into
    ``SELECT ... FROM events e WHERE <where_sql>`` — all user values are bound as
    parameters. ``session_id`` (when given) is AND-ed as a hard scope.
    """
    pf = parse_filter(query)
    wheres: List[str] = []
    params: List[str] = []
    if session_id is not None:
        wheres.append("e.session_id = ?")
        params.append(session_id)
    for cl in pf.clauses:
        if cl.key in _COLUMN_KEYS:
            col = _COLUMN_KEYS[cl.key]
            if "," in cl.value:
                vals = [v.strip() for v in cl.value.split(",") if v.strip()]
                if not vals:
                    pf.errors.append(f"empty value list for {cl.key}")
                    continue
                ph = ",".join("?" for _ in vals)
                wheres.append(
                    f"e.{col} NOT IN ({ph})" if cl.negate else f"e.{col} IN ({ph})"
                )
                params.extend(vals)
            else:
                if cl.negate:
                    wheres.append(f"(e.{col} IS NULL OR e.{col} != ?)")
                else:
                    wheres.append(f"e.{col} = ?")
                params.append(cl.value)
        elif cl.key in _TEXT_KEYS:
            pat = _like_pattern(cl.value)
            if cl.negate:
                wheres.append("e.payload NOT LIKE ? ESCAPE '\\'")
            else:
                wheres.append("e.payload LIKE ? ESCAPE '\\'")
            params.append(pat)
    for term in pf.free:
        wheres.append("e.payload LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(term))
    where_sql = " AND ".join(wheres) if wheres else "1=1"
    return where_sql, params, pf.errors


__all__ = [
    "Clause",
    "ParsedFilter",
    "parse_filter",
    "compile_event_filter",
]
