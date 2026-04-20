"""F-CEN-022: Adversarial DSL corpus + identifier interpolation tests.

Covers the attack surface of `alerting/dsl.py` — every place the compiler
interpolates a name or operator into ClickHouse SQL. The defence in depth
is two-layered:

1. The tokenizer (`_TOKEN_RE`) rejects anything outside the strict lex.
2. The compiler's `_assert_safe_identifier` re-checks every identifier
   right before emission. If the tokenizer is ever relaxed (e.g. someone
   opens the regex to unicode for i18n), the compiler still refuses.

The tests here exercise both paths: some adversarial inputs should be
rejected at parse, others at compile. Both outcomes are green as long as
we never produce SQL with a malicious identifier.
"""

from __future__ import annotations

import pytest

from monctl_central.alerting.dsl import (
    ParseError,
    _assert_safe_identifier,
    compile_to_sql,
    parse_expression,
)


# ── Positive path: known-good expressions compile ────────

_GOOD_CASES = [
    # (expression, target_table)
    ("avg(rtt_ms) > 80", "availability_latency"),
    ("max(rtt_ms) > 500 AND avg(rtt_ms) > 100", "availability_latency"),
    ("rate(in_octets) * 8 / 1e6 > 500", "interface"),
    ("last(cpu_idle) < 10", "performance"),
    ("avg(rtt_ms) > rtt_ms_warn", "availability_latency"),
    ("state != 'ok'", "config"),
    ("state IN ('warning', 'critical')", "config"),
    ("state NOT IN ('ok')", "config"),
]


@pytest.mark.parametrize("expr,table", _GOOD_CASES)
def test_good_expressions_compile(expr: str, table: str) -> None:
    ast = parse_expression(expr)
    compiled = compile_to_sql(ast, table, "5m")
    assert compiled.sql
    # No stray quotes from the expression leaked into the SQL text
    assert "';" not in compiled.sql
    assert "--" not in compiled.sql


# ── Negative path: the adversarial corpus ────────────────

_BAD_PARSE_CASES = [
    # Classic SQL tricks — rejected by the tokenizer
    "rtt_ms; DROP TABLE users --",
    "rtt_ms) OR 1=1 --",
    "rtt_ms' OR '1'='1",
    "avg(rtt_ms); SELECT 1",
    # Quote smuggling in strings
    "state = 'x' OR '1'='1",
    # Comment smuggling
    "avg(rtt_ms) /* bye */ > 80",
    # Whitespace tricks that look like identifiers but aren't
    "avg(rtt\nms) > 80",
    "avg(rtt\x00ms) > 80",
    # Unicode homoglyphs (Cyrillic А, Greek ο) — tokenizer is ASCII-only
    "avg(rttА_ms) > 80",  # noqa: RUF001 - Cyrillic А, intentional
    # Identifier starting with digit
    "avg(1_minute) > 80",
    # Arithmetic where identifier expected
    "avg(rtt+ms) > 80",
    # Nested quote
    "state = 'it''s'",
    # Empty identifier
    "avg() > 80",
    # Unknown aggregation function
    "median(rtt_ms) > 80",
    # CHANGED with garbage identifier
    "rtt_ms' CHANGED",
]


@pytest.mark.parametrize("expr", _BAD_PARSE_CASES)
def test_adversarial_expressions_rejected(expr: str) -> None:
    with pytest.raises(ParseError):
        ast = parse_expression(expr)
        # If parse succeeded (shouldn't), compile must reject
        compile_to_sql(ast, "availability_latency", "5m")


# ── Defense-in-depth on the identifier guard ─────────────

_BAD_IDENTS = [
    "'; DROP TABLE users; --",
    "x'; DELETE --",
    "x)",
    "x }",
    "x'",
    "x\"",
    "x;y",
    "",
    "1x",            # starts with digit
    "x" * 200,       # too long (IDENTIFIER_MAX_LENGTH)
    "rttА_ms",       # noqa: RUF001 - Cyrillic А
    "rtt-ms",
    "rtt.ms",
    "rtt ms",
]


@pytest.mark.parametrize("bad", _BAD_IDENTS)
def test_assert_safe_identifier_rejects(bad: str) -> None:
    with pytest.raises(ParseError):
        _assert_safe_identifier(bad, "test")


@pytest.mark.parametrize(
    "good",
    ["rtt_ms", "x", "X", "_leading_underscore", "snake_case_123", "abc"],
)
def test_assert_safe_identifier_accepts(good: str) -> None:
    assert _assert_safe_identifier(good, "test") == good


# ── Compile output never names a user identifier near a quote ──


def test_no_unbalanced_quotes_in_compiled_sql() -> None:
    ast = parse_expression("state == 'critical'")
    compiled = compile_to_sql(ast, "config", "5m")
    # The config_value comparison should use a parameter slot, not a literal
    assert "{_str_val_0:String}" in compiled.sql
    # And the fixed config_key literal must be exactly the identifier we parsed
    assert "config_key = 'state'" in compiled.sql
