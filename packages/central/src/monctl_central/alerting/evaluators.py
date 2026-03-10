"""Alert rule evaluators — translate rules into ClickHouse queries.

Each evaluator takes an AlertRule and returns a set of assignment_ids
that are currently in a firing state.
"""

from __future__ import annotations

import logging

from monctl_central.storage.clickhouse import ClickHouseClient
from monctl_central.storage.models import AlertRule

logger = logging.getLogger(__name__)


class ThresholdEvaluator:
    """Evaluates threshold-based rules.

    Condition format:
    {
        "metric": "rtt_ms",           # column name in check_results
        "op": ">",                     # >, <, >=, <=, ==, !=
        "value": 100,                  # threshold value
        "for": "5m",                   # evaluation window
        "agg": "avg"                   # avg, max, min, sum, count (default: avg)
    }
    """

    _VALID_OPS = {">", "<", ">=", "<=", "==", "!="}
    _VALID_AGGS = {"avg", "max", "min", "sum", "count"}

    def evaluate(self, rule: AlertRule, ch: ClickHouseClient) -> set[str]:
        cond = rule.condition
        metric = cond.get("metric", "rtt_ms")
        op = cond.get("op", ">")
        value = cond.get("value", 0)
        window = cond.get("for", "5m")
        agg = cond.get("agg", "avg")

        if op not in self._VALID_OPS:
            logger.warning("invalid_op", op=op, rule_id=str(rule.id))
            return set()
        if agg not in self._VALID_AGGS:
            agg = "avg"

        # Parse window string (e.g. "5m", "1h", "30s")
        interval = _parse_interval(window)

        # Map == to = for ClickHouse SQL
        ch_op = "=" if op == "==" else op

        sql = (
            f"SELECT toString(assignment_id) AS aid, {agg}({metric}) AS val "
            f"FROM check_results "
            f"WHERE executed_at > now() - INTERVAL {interval} "
            f"GROUP BY assignment_id "
            f"HAVING val {ch_op} {{threshold:Float64}}"
        )

        rows = ch.query_for_alert(sql, {"threshold": float(value)})
        return {r["aid"] for r in rows}


class StateChangeEvaluator:
    """Evaluates state-change rules.

    Condition format:
    {
        "to": 2       # target state (0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN)
    }
    """

    def evaluate(self, rule: AlertRule, ch: ClickHouseClient) -> set[str]:
        cond = rule.condition
        target_state = cond.get("to", 2)

        sql = (
            "SELECT toString(assignment_id) AS aid "
            "FROM check_results_latest FINAL "
            "WHERE state = {target_state:UInt8}"
        )

        rows = ch.query_for_alert(sql, {"target_state": target_state})
        return {r["aid"] for r in rows}


class AbsenceEvaluator:
    """Evaluates absence rules — assignments that haven't reported recently.

    Condition format:
    {
        "missing_for": "10m"    # how long the assignment must be missing
    }
    """

    def evaluate(self, rule: AlertRule, ch: ClickHouseClient) -> set[str]:
        cond = rule.condition
        missing_for = cond.get("missing_for", "10m")
        interval = _parse_interval(missing_for)

        sql = (
            "SELECT toString(assignment_id) AS aid, max(executed_at) AS last_exec "
            "FROM check_results "
            "GROUP BY assignment_id "
            f"HAVING last_exec < now() - INTERVAL {interval}"
        )

        rows = ch.query_for_alert(sql)
        return {r["aid"] for r in rows}


def _parse_interval(s: str) -> str:
    """Parse '5m', '1h', '30s', '2d' into ClickHouse INTERVAL format like '5 MINUTE'."""
    s = s.strip()
    if not s:
        return "5 MINUTE"

    units = {"s": "SECOND", "m": "MINUTE", "h": "HOUR", "d": "DAY"}
    suffix = s[-1].lower()
    if suffix in units:
        try:
            num = int(s[:-1])
            return f"{num} {units[suffix]}"
        except ValueError:
            pass
    return "5 MINUTE"
