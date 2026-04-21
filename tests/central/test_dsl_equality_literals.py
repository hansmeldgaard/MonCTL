"""Regression: equality comparisons against inline values must NOT collide
across tiers of the same definition via a shared auto-named threshold var.

Before the fix, `reachable == 0` and `reachable == 1` both auto-generated
the threshold variable `reachable_threshold`. `threshold_sync` dedupes by
name, so the two tiers shared a single row whose `default_value` was the
last-synced tier's inline value. At eval time both tier queries referenced
the same param key, so whichever value was in the PG row was substituted
into BOTH the fire-tier and the healthy-tier HAVING — one tier always
matched current data and pinned the alert to a single state.

The fix: compile `== N` / `!= N` with an inline numeric RHS to a literal
in HAVING, and skip the threshold-param registration entirely. Named refs
(e.g. `reachable == some_var`) still go through the param path.
"""

from __future__ import annotations

from monctl_central.alerting.dsl import (
    compile_to_sql,
    parse_expression,
    validate_expression,
)


def test_equality_inline_emits_literal_not_param() -> None:
    ast = parse_expression("reachable == 0")
    compiled = compile_to_sql(ast, "availability_latency", "5m")
    # No threshold param registered for inline equality — the fix.
    assert compiled.threshold_params == []
    # HAVING uses a literal, not a {param:Float64} placeholder.
    assert "= 0" in compiled.sql
    assert "Float64" not in compiled.sql


def test_equality_inline_one_and_zero_differ() -> None:
    """The tiers of `Ping - Device Unreachable` must compile to DIFFERENT
    HAVING clauses even though both reference the same metric."""
    crit = compile_to_sql(
        parse_expression("reachable == 0"), "availability_latency", "5m",
    )
    healthy = compile_to_sql(
        parse_expression("reachable == 1"), "availability_latency", "5m",
    )
    assert "= 0" in crit.sql
    assert "= 1" in healthy.sql
    assert crit.sql != healthy.sql
    # Neither registers a threshold param — so threshold_sync cannot
    # create a shared `reachable_threshold` variable.
    assert crit.threshold_params == []
    assert healthy.threshold_params == []


def test_inequality_inline_emits_literal() -> None:
    ast = parse_expression("reachable != 1")
    compiled = compile_to_sql(ast, "availability_latency", "5m")
    assert compiled.threshold_params == []
    assert "!= 1" in compiled.sql


def test_relational_inline_still_registers_threshold_param() -> None:
    """Relational comparisons with inline values are legitimate tunable
    thresholds — keep the auto-promoted threshold param behaviour."""
    ast = parse_expression("rtt_ms > 500")
    compiled = compile_to_sql(ast, "availability_latency", "5m")
    assert len(compiled.threshold_params) == 1
    tp = compiled.threshold_params[0]
    assert tp.name == "rtt_ms_threshold"
    assert tp.default_value == 500.0
    # HAVING uses a param placeholder — still tunable.
    assert "Float64" in compiled.sql


def test_named_threshold_ref_still_honoured_for_equality() -> None:
    """`reachable == some_var` with a NAMED ref should still emit a param
    so operators can switch the comparison value via a threshold variable."""
    ast = parse_expression("reachable == reachable_expected")
    compiled = compile_to_sql(ast, "availability_latency", "5m")
    # Named ref registered as a param.
    assert len(compiled.threshold_params) == 1
    assert compiled.threshold_params[0].name == "reachable_expected"
    assert "reachable_expected:Float64" in compiled.sql


def test_validate_expression_skips_threshold_ref_for_equality_inline() -> None:
    """validate_expression feeds `threshold_sync`. For inline equality it
    must not return a threshold_ref, otherwise sync would still try to
    create a shared `<metric>_threshold` variable."""
    res = validate_expression("reachable == 0", "availability_latency")
    assert res.valid
    assert res.threshold_refs == []
    # validate_expression should still return a threshold_ref for
    # relational inlines (legitimate tunable threshold).
    res_relational = validate_expression("rtt_ms > 100", "availability_latency")
    assert res_relational.valid
    assert len(res_relational.threshold_refs) == 1
