"""DSL parser and ClickHouse SQL compiler for alert expressions.

Grammar:
    expression     := condition (("AND" | "OR") condition)*
    condition      := agg_call COMPARE_OP value
                   |  identifier "CHANGED"
                   |  identifier "IN" "(" value_list ")"
                   |  identifier COMPARE_OP string_value
                   |  "(" expression ")"
    agg_call       := AGG_FUNC "(" identifier ")"
    AGG_FUNC       := "avg" | "max" | "min" | "sum" | "count" | "last"
    COMPARE_OP     := ">" | "<" | ">=" | "<=" | "==" | "!="
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── AST Nodes ────────────────────────────────────────────

@dataclass
class AggCall:
    func: str
    metric: str

@dataclass
class Comparison:
    left: AggCall | str
    op: str
    right: float | str

@dataclass
class Changed:
    identifier: str

@dataclass
class InList:
    identifier: str
    values: list[str]
    negated: bool = False  # True for NOT IN

@dataclass
class BoolOp:
    op: str  # "AND" | "OR"
    left: "ASTNode"
    right: "ASTNode"

ASTNode = Comparison | Changed | InList | BoolOp


# ── Tokenizer ────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    (?P<LPAREN>\()
    |(?P<RPAREN>\))
    |(?P<COMMA>,)
    |(?P<OP>[><!]=?|==)
    |(?P<NUMBER>-?\d+(?:\.\d+)?)
    |(?P<STRING>'[^']*'|"[^"]*")
    |(?P<WORD>[a-zA-Z_]\w*)
    |(?P<WS>\s+)
    """,
    re.VERBOSE,
)

_AGG_FUNCS = {"avg", "max", "min", "sum", "count", "last"}
_KEYWORDS = {"AND", "OR", "IN", "NOT", "CHANGED"}


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ParseError(f"Unexpected character at position {pos}: '{expr[pos]}'")
        pos = m.end()
        if m.lastgroup == "WS":
            continue
        value = m.group()
        if m.lastgroup == "WORD":
            upper = value.upper()
            if upper in _KEYWORDS:
                tokens.append(("KEYWORD", upper))
            elif value.lower() in _AGG_FUNCS:
                tokens.append(("AGG_FUNC", value.lower()))
            else:
                tokens.append(("IDENT", value))
        elif m.lastgroup == "STRING":
            tokens.append(("STRING", value[1:-1]))
        elif m.lastgroup == "NUMBER":
            tokens.append(("NUMBER", value))
        elif m.lastgroup == "OP":
            tokens.append(("OP", value))
        else:
            tokens.append((m.lastgroup, value))  # type: ignore[arg-type]
    return tokens


class ParseError(Exception):
    pass


# ── Recursive-descent parser ─────────────────────────────

class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self, expected_type: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ParseError("Unexpected end of expression")
        if expected_type and tok[0] != expected_type:
            raise ParseError(f"Expected {expected_type}, got {tok[0]} ('{tok[1]}')")
        self.pos += 1
        return tok

    def parse(self) -> ASTNode:
        node = self._parse_expression()
        if self.pos < len(self.tokens):
            raise ParseError(f"Unexpected token: '{self.tokens[self.pos][1]}'")
        return node

    def _parse_expression(self) -> ASTNode:
        left = self._parse_condition()
        while True:
            tok = self.peek()
            if tok and tok[0] == "KEYWORD" and tok[1] in ("AND", "OR"):
                self.consume()
                right = self._parse_condition()
                left = BoolOp(op=tok[1], left=left, right=right)
            else:
                break
        return left

    def _parse_condition(self) -> ASTNode:
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected condition, got end of expression")

        # Parenthesized sub-expression
        if tok[0] == "LPAREN":
            self.consume()
            node = self._parse_expression()
            self.consume("RPAREN")
            return node

        # Aggregation call: avg(metric) > value
        if tok[0] == "AGG_FUNC":
            return self._parse_agg_comparison()

        # Identifier: could be CHANGED, IN, or comparison with string
        if tok[0] == "IDENT":
            ident = self.consume()[1]
            next_tok = self.peek()
            if next_tok and next_tok[0] == "KEYWORD" and next_tok[1] == "CHANGED":
                self.consume()
                return Changed(identifier=ident)
            if next_tok and next_tok[0] == "KEYWORD" and next_tok[1] == "NOT":
                # NOT IN (...)
                self.consume()  # consume NOT
                nin_tok = self.peek()
                if nin_tok and nin_tok[0] == "KEYWORD" and nin_tok[1] == "IN":
                    self.consume()  # consume IN
                    self.consume("LPAREN")
                    values = self._parse_value_list()
                    self.consume("RPAREN")
                    return InList(identifier=ident, values=values, negated=True)
                raise ParseError(f"Expected 'IN' after 'NOT', got '{nin_tok[1] if nin_tok else 'end'}'")
            if next_tok and next_tok[0] == "KEYWORD" and next_tok[1] == "IN":
                self.consume()
                self.consume("LPAREN")
                values = self._parse_value_list()
                self.consume("RPAREN")
                return InList(identifier=ident, values=values)
            if next_tok and next_tok[0] == "OP":
                op = self.consume()[1]
                right = self._parse_value()
                return Comparison(left=ident, op=op, right=right)
            raise ParseError(f"Expected operator after '{ident}'")

        raise ParseError(f"Unexpected token: '{tok[1]}'")

    def _parse_agg_comparison(self) -> Comparison:
        func = self.consume("AGG_FUNC")[1]
        self.consume("LPAREN")
        metric_tok = self.peek()
        if metric_tok is None or metric_tok[0] != "IDENT":
            raise ParseError("Expected metric name inside aggregation function")
        metric = self.consume("IDENT")[1]
        self.consume("RPAREN")
        op = self.consume("OP")[1]
        right = self._parse_value()
        return Comparison(left=AggCall(func=func, metric=metric), op=op, right=right)

    def _parse_value(self) -> float | str:
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected value")
        if tok[0] == "NUMBER":
            self.consume()
            return float(tok[1]) if "." in tok[1] else float(tok[1])
        if tok[0] == "STRING":
            self.consume()
            return tok[1]
        raise ParseError(f"Expected number or string, got '{tok[1]}'")

    def _parse_value_list(self) -> list[str]:
        values: list[str] = []
        tok = self.peek()
        if tok and tok[0] == "STRING":
            values.append(self.consume("STRING")[1])
        elif tok and tok[0] == "NUMBER":
            values.append(self.consume("NUMBER")[1])
        else:
            raise ParseError("Expected value in IN list")
        while True:
            tok = self.peek()
            if tok and tok[0] == "COMMA":
                self.consume()
                tok2 = self.peek()
                if tok2 and tok2[0] == "STRING":
                    values.append(self.consume("STRING")[1])
                elif tok2 and tok2[0] == "NUMBER":
                    values.append(self.consume("NUMBER")[1])
                else:
                    raise ParseError("Expected value after comma in IN list")
            else:
                break
        return values


def parse_expression(expression: str) -> ASTNode:
    """Parse a DSL expression string into an AST."""
    expression = expression.strip()
    if not expression:
        raise ParseError("Empty expression")
    tokens = _tokenize(expression)
    if not tokens:
        raise ParseError("Empty expression")
    return _Parser(tokens).parse()


# ── Compiler: AST → ClickHouse SQL ────────────────────────

_TABLE_GROUP_BY = {
    "availability_latency": ["assignment_id"],
    "performance": ["device_id", "component_type", "component"],
    "interface": ["device_id", "interface_id"],
    "config": ["device_id", "config_key"],
}

_TABLE_LABEL_COLUMNS = {
    "availability_latency": ["any(device_name) AS device_name"],
    "performance": ["any(device_name) AS device_name"],
    "interface": ["any(device_name) AS device_name", "any(if_name) AS if_name"],
    "config": ["any(device_name) AS device_name"],
}


@dataclass
class ThresholdParam:
    name: str
    default_value: float
    param_key: str


@dataclass
class CompiledQuery:
    sql: str
    params: dict
    threshold_params: list[ThresholdParam]
    is_config_changed: bool = False
    config_changed_key: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None
    referenced_metrics: list[str] = field(default_factory=list)
    threshold_params: list[ThresholdParam] = field(default_factory=list)
    has_aggregation: bool = True


def validate_expression(expression: str, target_table: str) -> ValidationResult:
    """Validate a DSL expression and extract metadata."""
    try:
        ast = parse_expression(expression)
    except ParseError as e:
        return ValidationResult(valid=False, error=str(e))

    metrics: list[str] = []
    thresholds: list[ThresholdParam] = []
    has_agg = False
    _counter = [0]

    def _walk(node: ASTNode) -> None:
        nonlocal has_agg
        if isinstance(node, Comparison):
            if isinstance(node.left, AggCall):
                has_agg = True
                metrics.append(node.left.metric)
                if isinstance(node.right, (int, float)):
                    key = f"_threshold_{_counter[0]}"
                    name = f"{node.left.metric}_{node.left.func}_threshold"
                    thresholds.append(ThresholdParam(
                        name=name, default_value=float(node.right), param_key=key
                    ))
                    _counter[0] += 1
            elif isinstance(node.left, str):
                metrics.append(node.left)
        elif isinstance(node, Changed):
            has_agg = False
            metrics.append(node.identifier)
        elif isinstance(node, InList):
            has_agg = False
            metrics.append(node.identifier)
        elif isinstance(node, BoolOp):
            _walk(node.left)
            _walk(node.right)

    _walk(ast)

    return ValidationResult(
        valid=True,
        referenced_metrics=metrics,
        threshold_params=thresholds,
        has_aggregation=has_agg,
    )


class _Compiler:
    """Compiles an AST into a ClickHouse SQL query."""

    def __init__(self, target_table: str, window: str):
        self.target_table = target_table
        self.window = window
        self.params: dict = {}
        self.threshold_params: list[ThresholdParam] = []
        self._threshold_idx = 0
        self._str_idx = 0

    def compile(self, ast: ASTNode) -> CompiledQuery:
        # Config CHANGED special case
        if isinstance(ast, Changed):
            return CompiledQuery(
                sql="",
                params={},
                threshold_params=[],
                is_config_changed=True,
                config_changed_key=ast.identifier,
            )

        group_by = _TABLE_GROUP_BY.get(self.target_table, ["assignment_id"])
        label_cols = _TABLE_LABEL_COLUMNS.get(self.target_table, [])

        # Collect aggregation selects and HAVING clauses
        agg_selects: list[str] = []
        having_parts: list[str] = []
        where_extras: list[str] = []

        self._build_query_parts(ast, agg_selects, having_parts, where_extras)

        # Build SELECT columns
        select_cols = [f"toString({col}) AS {col}" for col in group_by]
        select_cols.extend(agg_selects)
        select_cols.extend(label_cols)

        # For config table with string comparisons (not CHANGED)
        if self.target_table == "config" and not agg_selects:
            return self._compile_config_string(ast, group_by, label_cols)

        interval = _parse_interval(self.window)

        # Performance table needs has() filter
        table = self.target_table
        where_clause = f"executed_at > now() - INTERVAL {interval}"
        if where_extras:
            where_clause += " AND " + " AND ".join(where_extras)

        group_by_str = ", ".join(group_by)
        having_str = " AND ".join(having_parts) if having_parts else "1"

        sql = (
            f"SELECT {', '.join(select_cols)} "
            f"FROM {table} "
            f"WHERE {where_clause} "
            f"GROUP BY {group_by_str} "
            f"HAVING {having_str}"
        )

        return CompiledQuery(
            sql=sql,
            params=self.params,
            threshold_params=self.threshold_params,
        )

    def _build_query_parts(
        self,
        node: ASTNode,
        agg_selects: list[str],
        having_parts: list[str],
        where_extras: list[str],
    ) -> None:
        if isinstance(node, Comparison) and isinstance(node.left, AggCall):
            agg = node.left
            idx = self._threshold_idx

            # Performance table: metric_values[indexOf(metric_names, 'metric')]
            if self.target_table == "performance":
                agg_expr = (
                    f"{agg.func}(metric_values[indexOf(metric_names, '{agg.metric}')])"
                )
                where_extras.append(f"has(metric_names, '{agg.metric}')")
            else:
                agg_expr = f"{agg.func}({agg.metric})"

            alias = f"_agg_{idx}"
            agg_selects.append(f"{agg_expr} AS {alias}")

            ch_op = "=" if node.op == "==" else node.op
            param_key = f"_threshold_{idx}"
            having_parts.append(f"{alias} {ch_op} {{{param_key}:Float64}}")

            self.params[param_key] = float(node.right) if isinstance(node.right, (int, float)) else 0.0

            name = f"{agg.metric}_{agg.func}_threshold"
            self.threshold_params.append(ThresholdParam(
                name=name,
                default_value=self.params[param_key],
                param_key=param_key,
            ))
            self._threshold_idx += 1

        elif isinstance(node, BoolOp):
            self._build_query_parts(node.left, agg_selects, having_parts, where_extras)
            self._build_query_parts(node.right, agg_selects, having_parts, where_extras)

    def _compile_config_string(
        self,
        ast: ASTNode,
        group_by: list[str],
        label_cols: list[str],
    ) -> CompiledQuery:
        """Compile config-table string comparisons (!=, ==, IN)."""
        select_cols = [f"toString({col}) AS {col}" for col in group_by]
        select_cols.append("config_value")
        select_cols.extend(label_cols)

        where_parts: list[str] = []
        self._build_config_where(ast, where_parts)

        sql = (
            f"SELECT {', '.join(select_cols)} "
            f"FROM config_latest FINAL "
            f"WHERE {' AND '.join(where_parts)}"
        )
        return CompiledQuery(sql=sql, params=self.params, threshold_params=[])

    def _build_config_where(self, node: ASTNode, parts: list[str]) -> None:
        if isinstance(node, Comparison) and isinstance(node.left, str):
            ch_op = "=" if node.op == "==" else node.op
            param_key = f"_str_val_{self._str_idx}"
            parts.append(f"config_key = '{node.left}'")
            parts.append(f"config_value {ch_op} {{{param_key}:String}}")
            self.params[param_key] = str(node.right)
            self._str_idx += 1
        elif isinstance(node, InList):
            param_keys = []
            for i, val in enumerate(node.values):
                pk = f"_in_val_{self._str_idx}_{i}"
                self.params[pk] = val
                param_keys.append(f"{{{pk}:String}}")
            op_str = "NOT IN" if node.negated else "IN"
            parts.append(f"config_key = '{node.identifier}'")
            parts.append(f"config_value {op_str} ({', '.join(param_keys)})")
            self._str_idx += 1
        elif isinstance(node, BoolOp):
            self._build_config_where(node.left, parts)
            self._build_config_where(node.right, parts)


def compile_to_sql(ast: ASTNode, target_table: str, window: str) -> CompiledQuery:
    """Compile a parsed AST into a ClickHouse SQL query."""
    compiler = _Compiler(target_table, window)
    return compiler.compile(ast)


def _parse_interval(s: str) -> str:
    """Parse '5m', '1h', '30s', '2d' into ClickHouse INTERVAL format."""
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


# ── Expression inversion (for recovery alerts) ───────────

_INVERT_OPS = {
    ">": "<=",
    "<": ">=",
    ">=": "<",
    "<=": ">",
    "==": "!=",
    "!=": "==",
}


def _ast_to_string(node: ASTNode) -> str:
    """Convert an AST node back to a DSL expression string."""
    if isinstance(node, Comparison):
        if isinstance(node.left, AggCall):
            left_str = f"{node.left.func}({node.left.metric})"
        else:
            left_str = node.left
        if isinstance(node.right, str):
            right_str = f"'{node.right}'"
        else:
            # Format number without trailing .0 if integer
            right_str = str(int(node.right)) if node.right == int(node.right) else str(node.right)
        return f"{left_str} {node.op} {right_str}"
    elif isinstance(node, Changed):
        return f"{node.identifier} CHANGED"
    elif isinstance(node, InList):
        vals = ", ".join(f"'{v}'" for v in node.values)
        op = "NOT IN" if node.negated else "IN"
        return f"{node.identifier} {op} ({vals})"
    elif isinstance(node, BoolOp):
        left = _ast_to_string(node.left)
        right = _ast_to_string(node.right)
        return f"{left} {node.op} {right}"
    return str(node)


def _invert_ast(node: ASTNode) -> ASTNode:
    """Invert an AST node for recovery alert generation."""
    if isinstance(node, Comparison):
        inv_op = _INVERT_OPS.get(node.op)
        if inv_op is None:
            raise ValueError(f"Cannot invert operator: {node.op}")
        return Comparison(left=node.left, op=inv_op, right=node.right)
    elif isinstance(node, Changed):
        raise ValueError("Cannot invert CHANGED expressions")
    elif isinstance(node, InList):
        return InList(identifier=node.identifier, values=node.values, negated=not node.negated)
    elif isinstance(node, BoolOp):
        return BoolOp(op=node.op, left=_invert_ast(node.left), right=_invert_ast(node.right))
    raise ValueError(f"Unknown AST node type: {type(node)}")


def invert_expression(expression: str) -> str:
    """Parse an expression, invert all comparisons, and return the inverted string.

    Raises ValueError if the expression cannot be inverted (e.g. CHANGED-only).
    """
    ast = parse_expression(expression)
    inverted = _invert_ast(ast)
    return _ast_to_string(inverted)
