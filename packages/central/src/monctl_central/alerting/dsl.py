"""DSL parser and ClickHouse SQL compiler for alert expressions.

Grammar:
    expression     := condition (("AND" | "OR") condition)*

    condition      := arith_expr COMPARE_OP threshold_ref
                   |  identifier "CHANGED"
                   |  identifier "IN" "(" value_list ")"
                   |  identifier "NOT" "IN" "(" value_list ")"
                   |  identifier COMPARE_OP string_value
                   |  "(" expression ")"

    arith_expr     := arith_term (("+" | "-") arith_term)*
    arith_term     := arith_atom (("*" | "/") arith_atom)*
    arith_atom     := agg_call
                   |  number
                   |  "(" arith_expr ")"

    threshold_ref  := NUMBER   (inline value, auto-creates threshold variable)
                   |  IDENTIFIER  (named reference, looks up existing variable)

    agg_call       := AGG_FUNC "(" identifier ")"
    AGG_FUNC       := "avg" | "max" | "min" | "sum" | "count" | "last" | "rate"
    COMPARE_OP     := ">" | "<" | ">=" | "<=" | "==" | "!="
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Union

# ── Safety limits ────────────────────────────────────────

MAX_EXPRESSION_LENGTH = 2000
MAX_TOKEN_COUNT = 200
MAX_NESTING_DEPTH = 10
MAX_AGG_CALLS = 20
MAX_ARITH_OPS = 30
IDENTIFIER_MAX_LENGTH = 100


# ── AST Nodes ────────────────────────────────────────────

@dataclass
class AggCall:
    func: str   # "avg", "max", "min", "sum", "count", "last", "rate"
    metric: str


@dataclass
class ArithOp:
    op: str          # "+", "-", "*", "/"
    left: "ArithNode"
    right: "ArithNode"


@dataclass
class NumericLiteral:
    value: float


@dataclass
class ThresholdRef:
    """A reference to a threshold — either an inline value or a named variable."""
    name: str              # Auto-generated name for inline, user name for named refs
    inline_value: float | None  # The literal value for inline, None for named refs
    is_named: bool         # True if user wrote a name, False if inline value


ArithNode = Union[AggCall, ArithOp, NumericLiteral]


@dataclass
class Comparison:
    left: ArithNode | str       # ArithNode for numeric, str for config string
    op: str
    right: ThresholdRef | float | str


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
    |(?P<ARITH>[+\-*/])
    |(?P<NUMBER>-?\d+(?:\.\d+)?)
    |(?P<STRING>'[^']*'|"[^"]*")
    |(?P<WORD>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<WS>\s+)
    """,
    re.VERBOSE | re.ASCII,
)

# Belt-and-braces identifier guard. Every place the compiler interpolates
# an identifier into raw SQL runs the string through this regex again, so
# a future tokenizer bug (e.g. relaxing WORD to admit unicode/quotes) can't
# quietly turn into SQL injection. Keep the character class in sync with
# the WORD group above.
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _assert_safe_identifier(value: str, where: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENT_RE.match(value):
        raise ParseError(f"Invalid identifier in {where}: {value!r}")
    if len(value) > IDENTIFIER_MAX_LENGTH:
        raise ParseError(
            f"Identifier in {where} exceeds {IDENTIFIER_MAX_LENGTH} chars: {value!r}"
        )
    return value

_AGG_FUNCS = {"avg", "max", "min", "sum", "count", "last", "rate"}
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
        elif m.lastgroup == "ARITH":
            tokens.append(("ARITH", value))
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
        self._depth = 0
        self._agg_count = 0
        self._arith_count = 0

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

    def _enter_depth(self) -> None:
        self._depth += 1
        if self._depth > MAX_NESTING_DEPTH:
            raise ParseError(f"Maximum nesting depth ({MAX_NESTING_DEPTH}) exceeded")

    def _exit_depth(self) -> None:
        self._depth -= 1

    def _count_agg(self) -> None:
        self._agg_count += 1
        if self._agg_count > MAX_AGG_CALLS:
            raise ParseError(f"Maximum aggregation calls ({MAX_AGG_CALLS}) exceeded")

    def _count_arith(self) -> None:
        self._arith_count += 1
        if self._arith_count > MAX_ARITH_OPS:
            raise ParseError(f"Maximum arithmetic operations ({MAX_ARITH_OPS}) exceeded")

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

        # Parenthesized: could be boolean sub-expression OR start of arithmetic.
        # Use backtracking: try arithmetic first (since `(avg(x)+avg(y))*2 > 100`
        # needs to parse the `(` as arithmetic grouping, not boolean grouping).
        if tok[0] == "LPAREN":
            save_pos = self.pos
            save_depth = self._depth
            save_agg = self._agg_count
            save_arith = self._arith_count
            try:
                return self._parse_arith_comparison()
            except ParseError:
                # Restore state and try as boolean sub-expression
                self.pos = save_pos
                self._depth = save_depth
                self._agg_count = save_agg
                self._arith_count = save_arith
            self._enter_depth()
            self.consume()
            node = self._parse_expression()
            self.consume("RPAREN")
            self._exit_depth()
            return node

        # Bare identifier: could be CHANGED, IN, NOT IN, or string comparison
        if tok[0] == "IDENT":
            return self._parse_ident_condition()

        # Aggregation call or arithmetic expression starting with agg/number
        if tok[0] in ("AGG_FUNC", "NUMBER"):
            return self._parse_arith_comparison()

        raise ParseError(f"Unexpected token: '{tok[1]}'")

    def _parse_ident_condition(self) -> ASTNode:
        """Parse a condition starting with a bare identifier."""
        ident = self.consume("IDENT")[1]
        if len(ident) > IDENTIFIER_MAX_LENGTH:
            raise ParseError(f"Identifier '{ident[:20]}...' exceeds max length ({IDENTIFIER_MAX_LENGTH})")

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
            raise ParseError(
                f"Expected 'IN' after 'NOT', got '{nin_tok[1] if nin_tok else 'end'}'"
            )
        if next_tok and next_tok[0] == "KEYWORD" and next_tok[1] == "IN":
            self.consume()
            self.consume("LPAREN")
            values = self._parse_value_list()
            self.consume("RPAREN")
            return InList(identifier=ident, values=values)
        if next_tok and next_tok[0] == "OP":
            op = self.consume()[1]
            # Look ahead: if the right side is a NUMBER or a bare
            # identifier (threshold-variable reference), promote the
            # bare left identifier to `last(<ident>)` so operators can
            # write `rtt_ms > 50` or `rtt_ms > rtt_ms_warn` without
            # typing `last(...)` every time. STRING values keep the
            # legacy bare-ident string-comparison semantics (config
            # table only — semantic validator enforces).
            peek_rhs = self.peek()
            if peek_rhs and peek_rhs[0] in ("NUMBER", "IDENT"):
                self._count_agg()
                agg = AggCall(func="last", metric=ident)
                right_ref = self._parse_threshold_ref(agg)
                return Comparison(left=agg, op=op, right=right_ref)
            right = self._parse_value()
            return Comparison(left=ident, op=op, right=right)
        raise ParseError(f"Expected operator after '{ident}'")

    def _parse_arith_comparison(self) -> Comparison:
        """Parse: arith_expr COMPARE_OP threshold_ref."""
        arith = self._parse_arith_expr()
        op = self.consume("OP")[1]
        right = self._parse_threshold_ref(arith)
        return Comparison(left=arith, op=op, right=right)

    # ── Arithmetic expression parsing (precedence climbing) ──

    def _parse_arith_expr(self) -> ArithNode:
        """arith_expr := arith_term (("+" | "-") arith_term)*"""
        left = self._parse_arith_term()
        while True:
            tok = self.peek()
            if tok and tok[0] == "ARITH" and tok[1] in ("+", "-"):
                self._count_arith()
                self.consume()
                right = self._parse_arith_term()
                left = ArithOp(op=tok[1], left=left, right=right)
            else:
                break
        return left

    def _parse_arith_term(self) -> ArithNode:
        """arith_term := arith_atom (("*" | "/") arith_atom)*"""
        left = self._parse_arith_atom()
        while True:
            tok = self.peek()
            if tok and tok[0] == "ARITH" and tok[1] in ("*", "/"):
                self._count_arith()
                self.consume()
                right = self._parse_arith_atom()
                left = ArithOp(op=tok[1], left=left, right=right)
            else:
                break
        return left

    def _parse_arith_atom(self) -> ArithNode:
        """arith_atom := agg_call | number | "(" arith_expr ")" """
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected arithmetic operand, got end of expression")

        if tok[0] == "AGG_FUNC":
            return self._parse_agg_call()

        if tok[0] == "NUMBER":
            self.consume()
            return NumericLiteral(value=float(tok[1]))

        if tok[0] == "LPAREN":
            self._enter_depth()
            self.consume()
            expr = self._parse_arith_expr()
            self.consume("RPAREN")
            self._exit_depth()
            return expr

        raise ParseError(f"Expected aggregation, number, or '(', got '{tok[1]}'")

    def _parse_agg_call(self) -> AggCall:
        func = self.consume("AGG_FUNC")[1]
        self.consume("LPAREN")
        metric_tok = self.peek()
        if metric_tok is None or metric_tok[0] != "IDENT":
            raise ParseError("Expected metric name inside aggregation function")
        metric = self.consume("IDENT")[1]
        if len(metric) > IDENTIFIER_MAX_LENGTH:
            raise ParseError(f"Identifier '{metric[:20]}...' exceeds max length ({IDENTIFIER_MAX_LENGTH})")
        self.consume("RPAREN")
        self._count_agg()
        return AggCall(func=func, metric=metric)

    _threshold_index: int = 0

    def _parse_threshold_ref(self, left_ast: ArithNode) -> ThresholdRef | str:
        """Parse threshold reference: NUMBER (inline) or IDENTIFIER (named)."""
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected threshold value")
        if tok[0] == "NUMBER":
            self.consume()
            value = float(tok[1])
            name = _auto_threshold_name(left_ast, self._threshold_index)
            self._threshold_index += 1
            return ThresholdRef(name=name, inline_value=value, is_named=False)
        if tok[0] == "IDENT":
            self.consume()
            return ThresholdRef(name=tok[1], inline_value=None, is_named=True)
        if tok[0] == "STRING":
            self.consume()
            return tok[1]
        raise ParseError(f"Expected number, identifier, or string, got '{tok[1]}'")

    def _parse_value(self) -> float | str:
        tok = self.peek()
        if tok is None:
            raise ParseError("Expected value")
        if tok[0] == "NUMBER":
            self.consume()
            return float(tok[1])
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


def _auto_threshold_name(left_ast: ArithNode, index: int) -> str:
    """Generate a threshold variable name from the left side of a comparison."""
    if isinstance(left_ast, AggCall):
        return f"{left_ast.metric}_threshold"
    # Complex arithmetic — use positional fallback
    return f"_expr_{index}_threshold"


def parse_expression(expression: str) -> ASTNode:
    """Parse a DSL expression string into an AST."""
    expression = expression.strip()
    if not expression:
        raise ParseError("Empty expression")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ParseError(f"Expression exceeds maximum length ({MAX_EXPRESSION_LENGTH} characters)")
    tokens = _tokenize(expression)
    if not tokens:
        raise ParseError("Empty expression")
    if len(tokens) > MAX_TOKEN_COUNT:
        raise ParseError(f"Expression exceeds maximum token count ({MAX_TOKEN_COUNT})")
    return _Parser(tokens).parse()


# ── AST helpers ──────────────────────────────────────────

def _collect_agg_calls(node: ArithNode) -> list[AggCall]:
    """Recursively collect all AggCall nodes from an arithmetic tree."""
    if isinstance(node, AggCall):
        return [node]
    if isinstance(node, ArithOp):
        return _collect_agg_calls(node.left) + _collect_agg_calls(node.right)
    return []


def _has_agg_call(node: ArithNode) -> bool:
    """Check if an arithmetic tree contains at least one AggCall."""
    if isinstance(node, AggCall):
        return True
    if isinstance(node, ArithOp):
        return _has_agg_call(node.left) or _has_agg_call(node.right)
    # NumericLiteral: no agg
    return False


def _has_division(node: ArithNode) -> bool:
    """Check if an arithmetic tree contains division."""
    if isinstance(node, ArithOp):
        if node.op == "/":
            return True
        return _has_division(node.left) or _has_division(node.right)
    return False


def _has_self_div(node: ArithNode) -> bool:
    """Check for self-referencing division like avg(x) / avg(x)."""
    if isinstance(node, ArithOp) and node.op == "/":
        left_aggs = _collect_agg_calls(node.left)
        right_aggs = _collect_agg_calls(node.right)
        for la in left_aggs:
            for ra in right_aggs:
                if la.func == ra.func and la.metric == ra.metric:
                    return True
    if isinstance(node, ArithOp):
        return _has_self_div(node.left) or _has_self_div(node.right)
    return False


def _has_div_by_zero_constant(node: ArithNode) -> bool:
    """Check for division by a zero numeric literal."""
    if isinstance(node, ArithOp) and node.op == "/":
        if isinstance(node.right, NumericLiteral) and node.right.value == 0:
            return True
    if isinstance(node, ArithOp):
        return _has_div_by_zero_constant(node.left) or _has_div_by_zero_constant(node.right)
    return False


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

# Columns in the interface table that already have a _rate companion
_INTERFACE_RATE_COLUMNS = {
    "in_octets", "out_octets", "in_ucast_pkts", "out_ucast_pkts",
    "in_mcast_pkts", "out_mcast_pkts", "in_bcast_pkts", "out_bcast_pkts",
    "in_errors", "out_errors", "in_discards", "out_discards",
}

_COUNTER_SUFFIXES = ("_octets", "_pkts", "_bytes", "_count", "_total")

_VALID_WINDOWS = {"30s", "1m", "5m", "15m", "1h"}
_VALID_SEVERITIES = {"info", "warning", "critical", "emergency"}
_VALID_COMPARE_OPS = {">", "<", ">=", "<=", "==", "!="}


@dataclass
class ThresholdParam:
    name: str
    default_value: float
    param_key: str


@dataclass
class ThresholdRefInfo:
    name: str
    is_named: bool
    inline_value: float | None


@dataclass
class CompiledQuery:
    sql: str
    params: dict
    threshold_params: list[ThresholdParam]
    is_config_changed: bool = False
    config_changed_key: str | None = None
    metric_aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    referenced_metrics: list[str] = field(default_factory=list)
    threshold_params: list[ThresholdParam] = field(default_factory=list)
    has_aggregation: bool = True
    has_arithmetic: bool = False
    has_division: bool = False
    threshold_refs: list[ThresholdRefInfo] = field(default_factory=list)

    @property
    def error(self) -> str | None:
        """Backward compatibility: return first error or None."""
        return self.errors[0] if self.errors else None


def validate_expression(
    expression: str,
    target_table: str,
    *,
    window: str | None = None,
    severity: str | None = None,
    name: str | None = None,
) -> ValidationResult:
    """Validate a DSL expression and extract metadata.

    Parameters beyond expression/target_table are optional; when provided they
    trigger additional validation checks.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Basic checks ─────────────────────────────────────
    if not expression or not expression.strip():
        return ValidationResult(valid=False, errors=["Expression must not be empty"])

    if len(expression) > MAX_EXPRESSION_LENGTH:
        return ValidationResult(
            valid=False,
            errors=[f"Expression exceeds maximum length ({MAX_EXPRESSION_LENGTH} characters)"],
        )

    # ── Parse ────────────────────────────────────────────
    try:
        ast = parse_expression(expression)
    except ParseError as e:
        return ValidationResult(valid=False, errors=[str(e)])

    # ── Walk AST to collect metadata ─────────────────────
    metrics: list[str] = []
    thresholds: list[ThresholdParam] = []
    threshold_ref_infos: list[ThresholdRefInfo] = []
    has_agg = False
    has_arith = False
    has_div = False
    _counter = [0]

    def _walk_arith(node: ArithNode) -> None:
        nonlocal has_agg, has_arith, has_div
        if isinstance(node, AggCall):
            has_agg = True
            metrics.append(node.metric)
        elif isinstance(node, ArithOp):
            has_arith = True
            if node.op == "/":
                has_div = True
            _walk_arith(node.left)
            _walk_arith(node.right)
        # NumericLiteral: nothing to collect

    def _walk(node: ASTNode) -> None:
        nonlocal has_agg
        if isinstance(node, Comparison):
            if isinstance(node.left, str):
                # Config string comparison
                metrics.append(node.left)
            else:
                # ArithNode (AggCall, ArithOp, NumericLiteral)
                _walk_arith(node.left)
                if isinstance(node.right, ThresholdRef):
                    ref = node.right
                    threshold_ref_infos.append(ThresholdRefInfo(
                        name=ref.name,
                        is_named=ref.is_named,
                        inline_value=ref.inline_value,
                    ))
                    if ref.is_named:
                        # Named reference — param key is the name
                        thresholds.append(ThresholdParam(
                            name=ref.name, default_value=0.0, param_key=ref.name,
                        ))
                    else:
                        # Inline value — auto-generated param key
                        key = f"_threshold_{_counter[0]}"
                        thresholds.append(ThresholdParam(
                            name=ref.name,
                            default_value=ref.inline_value,
                            param_key=key,
                        ))
                        _counter[0] += 1
                elif isinstance(node.right, (int, float)):
                    # Backward compat: plain float from _parse_value (ident conditions)
                    key = f"_threshold_{_counter[0]}"
                    agg_calls = _collect_agg_calls(node.left) if not isinstance(node.left, str) else []
                    if agg_calls:
                        first = agg_calls[0]
                        tname = f"{first.metric}_{first.func}_threshold"
                    else:
                        tname = f"threshold_{_counter[0]}"
                    thresholds.append(ThresholdParam(
                        name=tname, default_value=float(node.right), param_key=key,
                    ))
                    _counter[0] += 1
        elif isinstance(node, Changed):
            metrics.append(node.identifier)
        elif isinstance(node, InList):
            metrics.append(node.identifier)
        elif isinstance(node, BoolOp):
            _walk(node.left)
            _walk(node.right)

    _walk(ast)

    # ── Semantic validations ─────────────────────────────
    # CHANGED/IN/string ops only for config table
    def _check_config_only(n: ASTNode) -> None:
        if isinstance(n, Changed) and target_table != "config":
            errors.append("CHANGED operator is only allowed for config table")
        elif isinstance(n, InList) and target_table != "config":
            errors.append("IN operator is only allowed for config table")
        elif isinstance(n, Comparison) and isinstance(n.left, str) and target_table != "config":
            errors.append("String comparisons are only allowed for config table")
        elif isinstance(n, BoolOp):
            _check_config_only(n.left)
            _check_config_only(n.right)

    _check_config_only(ast)

    # Non-config must have at least one agg_call
    if target_table != "config" and not has_agg:
        errors.append("Non-config expressions must contain at least one aggregation call")

    # No bare number/number without agg_call
    def _check_bare_arith(n: ASTNode) -> None:
        if isinstance(n, Comparison) and not isinstance(n.left, str):
            arith = n.left
            if isinstance(arith, (ArithOp, NumericLiteral)) and not _has_agg_call(arith):
                errors.append("Arithmetic expression must contain at least one aggregation call")
        elif isinstance(n, BoolOp):
            _check_bare_arith(n.left)
            _check_bare_arith(n.right)

    _check_bare_arith(ast)

    # Self-referencing division
    def _check_self_div(n: ASTNode) -> None:
        if isinstance(n, Comparison) and not isinstance(n.left, str):
            if _has_self_div(n.left):
                errors.append("Self-referencing division detected (e.g. avg(x) / avg(x))")
        elif isinstance(n, BoolOp):
            _check_self_div(n.left)
            _check_self_div(n.right)

    _check_self_div(ast)

    # Division by zero constant
    def _check_div_zero(n: ASTNode) -> None:
        if isinstance(n, Comparison) and not isinstance(n.left, str):
            if _has_div_by_zero_constant(n.left):
                errors.append("Division by zero constant detected")
        elif isinstance(n, BoolOp):
            _check_div_zero(n.left)
            _check_div_zero(n.right)

    _check_div_zero(ast)

    # Threshold is finite number (skip for named refs with default 0.0)
    for tp in thresholds:
        # Skip named-ref thresholds (they have name == param_key and default 0.0)
        if tp.name == tp.param_key and tp.default_value == 0.0:
            continue
        if not math.isfinite(tp.default_value):
            errors.append(f"Threshold value must be a finite number (got {tp.default_value})")

    # Percent metrics: threshold 0-100 with > or >=
    def _check_pct(n: ASTNode) -> None:
        if isinstance(n, Comparison) and not isinstance(n.left, str):
            agg_calls = _collect_agg_calls(n.left)
            for ac in agg_calls:
                if ac.metric.endswith("_pct") or ac.metric.endswith("_percent"):
                    # Skip range check for named refs (resolved at runtime)
                    if isinstance(n.right, ThresholdRef) and n.right.is_named:
                        continue
                    # Check inline threshold values
                    threshold_val = None
                    if isinstance(n.right, ThresholdRef) and n.right.inline_value is not None:
                        threshold_val = n.right.inline_value
                    elif isinstance(n.right, (int, float)):
                        threshold_val = float(n.right)
                    if threshold_val is not None:
                        if not (0 <= threshold_val <= 100):
                            errors.append(
                                f"Threshold for percentage metric '{ac.metric}' must be 0-100"
                            )
                        if n.op not in (">", ">="):
                            errors.append(
                                f"Percentage metric '{ac.metric}' should use > or >= operator"
                            )
        elif isinstance(n, BoolOp):
            _check_pct(n.left)
            _check_pct(n.right)

    _check_pct(ast)

    # Try compile to catch any compilation errors
    if not errors:
        try:
            compile_to_sql(ast, target_table, window or "5m")
        except Exception as e:
            errors.append(f"Expression compilation failed: {e}")

    # ── Optional field validations ───────────────────────
    if window is not None and window not in _VALID_WINDOWS:
        errors.append(f"Window must be one of: {', '.join(sorted(_VALID_WINDOWS))}")

    if severity is not None and severity not in _VALID_SEVERITIES:
        errors.append(f"Severity must be one of: {', '.join(sorted(_VALID_SEVERITIES))}")

    if name is not None:
        if not (1 <= len(name) <= 255):
            errors.append("Name must be 1-255 characters")

    # ── Warnings ─────────────────────────────────────────
    if has_div:
        warnings.append("Entities where divisor = 0 are automatically skipped")

    # rate() on non-counter metric
    def _check_rate_metrics(n: ASTNode) -> None:
        if isinstance(n, Comparison) and not isinstance(n.left, str):
            for ac in _collect_agg_calls(n.left):
                if ac.func == "rate" and not ac.metric.endswith(_COUNTER_SUFFIXES):
                    warnings.append(
                        f"rate() on '{ac.metric}' — consider using on counter metrics "
                        f"(ending in {', '.join(_COUNTER_SUFFIXES)})"
                    )
        elif isinstance(n, BoolOp):
            _check_rate_metrics(n.left)
            _check_rate_metrics(n.right)

    _check_rate_metrics(ast)

    if window == "30s":
        warnings.append("Window '30s' is a single poll cycle, consider '5m' for stability")

    if len(metrics) >= 5:
        warnings.append(
            f"Expression references {len(metrics)} metrics — consider splitting into separate alerts"
        )

    # Check for exclusive-range anti-pattern: metric > $warn AND metric < $crit
    def _arith_repr(node) -> str | None:
        """Stable string repr of an arithmetic subtree for equality comparison."""
        if isinstance(node, AggCall):
            return f"{node.func}({node.metric})"
        if isinstance(node, ArithOp):
            left = _arith_repr(node.left)
            right = _arith_repr(node.right)
            if left and right:
                return f"({left}{node.op}{right})"
        if isinstance(node, NumericLiteral):
            return str(node.value)
        return None

    def _check_exclusive_range(n: ASTNode) -> None:
        if isinstance(n, BoolOp) and n.op == "AND":
            if isinstance(n.left, Comparison) and isinstance(n.right, Comparison):
                left_repr = _arith_repr(n.left.left) if not isinstance(n.left.left, str) else None
                right_repr = _arith_repr(n.right.left) if not isinstance(n.right.left, str) else None
                if left_repr and right_repr and left_repr == right_repr:
                    gt_ops = {">", ">="}
                    lt_ops = {"<", "<="}
                    if (n.left.op in gt_ops and n.right.op in lt_ops) or \
                       (n.left.op in lt_ops and n.right.op in gt_ops):
                        warnings.append(
                            f"Exclusive range on {left_repr}: alert will clear when "
                            f"value crosses into the next severity band. "
                            f"Remove the upper bound to keep the alert active."
                        )
            _check_exclusive_range(n.left)
            _check_exclusive_range(n.right)
        elif isinstance(n, BoolOp):
            _check_exclusive_range(n.left)
            _check_exclusive_range(n.right)

    _check_exclusive_range(ast)

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        referenced_metrics=metrics,
        threshold_params=thresholds,
        has_aggregation=has_agg,
        has_arithmetic=has_arith,
        has_division=has_div,
        threshold_refs=threshold_ref_infos,
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
        self._arith_idx = 0
        self._agg_idx = 0
        # Collected during compilation
        self._metric_aliases: dict[str, str] = {}
        self._agg_selects: list[str] = []
        self._having_parts: list[str] = []
        self._where_extras: list[str] = []
        self._finite_checks: list[str] = []

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

        self._build_query_parts(ast)

        # Build SELECT columns
        select_cols = [f"toString({col}) AS {col}" for col in group_by]
        select_cols.extend(self._agg_selects)
        select_cols.extend(label_cols)

        # For config table with string comparisons (not CHANGED)
        if self.target_table == "config" and not self._agg_selects:
            return self._compile_config_string(ast, group_by, label_cols)

        interval = _parse_interval(self.window)

        table = self.target_table
        where_clause = f"executed_at > now() - INTERVAL {interval}"
        if self._where_extras:
            where_clause += " AND " + " AND ".join(self._where_extras)

        group_by_str = ", ".join(group_by)

        having_clauses = list(self._having_parts)
        if self._finite_checks:
            having_clauses.extend(self._finite_checks)
        having_str = " AND ".join(having_clauses) if having_clauses else "1"

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
            metric_aliases=self._metric_aliases,
        )

    def _build_query_parts(self, node: ASTNode) -> None:
        if isinstance(node, Comparison) and not isinstance(node.left, str):
            # Arithmetic / aggregation comparison
            arith_alias = self._compile_arith_select(node.left)

            if node.op not in _VALID_COMPARE_OPS:
                raise ParseError(f"Invalid comparison operator: {node.op!r}")
            ch_op = "=" if node.op == "==" else node.op

            if isinstance(node.right, ThresholdRef):
                ref = node.right
                if ref.is_named:
                    # Named reference — use ref name as param key
                    safe_name = _assert_safe_identifier(ref.name, "threshold name")
                    self._having_parts.append(
                        f"{arith_alias} {ch_op} {{{safe_name}:Float64}}"
                    )
                    self.params[safe_name] = 0.0  # default, resolved at runtime
                    self.threshold_params.append(ThresholdParam(
                        name=safe_name,
                        default_value=0.0,
                        param_key=safe_name,
                    ))
                else:
                    # Inline value — auto-generated param key
                    param_key = f"_threshold_{self._threshold_idx}"
                    self._having_parts.append(
                        f"{arith_alias} {ch_op} {{{param_key}:Float64}}"
                    )
                    self.params[param_key] = ref.inline_value
                    self.threshold_params.append(ThresholdParam(
                        name=ref.name,
                        default_value=ref.inline_value,
                        param_key=param_key,
                    ))
                    self._threshold_idx += 1
            elif isinstance(node.right, (int, float)):
                # Backward compat: plain float from ident conditions
                param_key = f"_threshold_{self._threshold_idx}"
                self._having_parts.append(
                    f"{arith_alias} {ch_op} {{{param_key}:Float64}}"
                )
                threshold_val = float(node.right)
                self.params[param_key] = threshold_val

                agg_calls = _collect_agg_calls(node.left)
                if agg_calls:
                    first = agg_calls[0]
                    tname = f"{first.metric}_{first.func}_threshold"
                else:
                    tname = f"threshold_{self._threshold_idx}"
                self.threshold_params.append(ThresholdParam(
                    name=tname,
                    default_value=threshold_val,
                    param_key=param_key,
                ))
                self._threshold_idx += 1

        elif isinstance(node, BoolOp):
            self._build_query_parts(node.left)
            self._build_query_parts(node.right)

    def _compile_arith_select(self, node: ArithNode) -> str:
        """Compile an ArithNode into a SQL expression, add to SELECT, return alias."""
        sql_expr = self._arith_to_sql(node)
        alias = f"_arith_{self._arith_idx}"
        self._agg_selects.append(f"{sql_expr} AS {alias}")
        self._arith_idx += 1

        # If the expression contains division, add isFinite check
        if isinstance(node, ArithOp) and _has_division(node):
            self._finite_checks.append(f"isFinite({alias})")

        # Track metric aliases for template rendering
        agg_calls = _collect_agg_calls(node)
        seen_metrics: dict[str, int] = {}
        for ac in agg_calls:
            seen_metrics[ac.metric] = seen_metrics.get(ac.metric, 0) + 1
        for ac in agg_calls:
            if seen_metrics[ac.metric] > 1:
                key = f"{ac.func}_{ac.metric}"
            else:
                key = ac.metric
            self._metric_aliases[key] = alias

        return alias

    def _arith_to_sql(self, node: ArithNode) -> str:
        """Recursively compile an ArithNode to SQL."""
        if isinstance(node, AggCall):
            return self._agg_to_sql(node)
        elif isinstance(node, NumericLiteral):
            return str(node.value)
        elif isinstance(node, ArithOp):
            left_sql = self._arith_to_sql(node.left)
            right_sql = self._arith_to_sql(node.right)
            if node.op == "/":
                return f"if(({right_sql}) = 0, nan, ({left_sql}) / ({right_sql}))"
            return f"({left_sql}) {node.op} ({right_sql})"
        raise ParseError(f"Unknown ArithNode type: {type(node)}")

    def _agg_to_sql(self, agg: AggCall) -> str:
        """Compile a single AggCall to SQL, registering WHERE extras as needed."""
        metric = _assert_safe_identifier(agg.metric, "agg metric")
        func = agg.func
        if func not in _AGG_FUNCS:
            raise ParseError(f"Unknown aggregation function: {func!r}")

        if func == "rate":
            return self._rate_to_sql(metric)

        # ClickHouse has no last() — use argMax(..., executed_at) instead
        if func == "last":
            if self.target_table == "performance":
                metric_ref = f"metric_values[indexOf(metric_names, '{metric}')]"
                self._where_extras.append(f"has(metric_names, '{metric}')")
            else:
                metric_ref = metric
            return f"argMax({metric_ref}, executed_at)"

        if self.target_table == "performance":
            expr = f"{func}(metric_values[indexOf(metric_names, '{metric}')])"
            self._where_extras.append(f"has(metric_names, '{metric}')")
        else:
            expr = f"{func}({metric})"

        return expr

    def _rate_to_sql(self, metric: str) -> str:
        """Compile rate(metric) to SQL."""
        metric = _assert_safe_identifier(metric, "rate metric")
        # Interface table: use pre-computed _rate column if available
        if self.target_table == "interface" and metric in _INTERFACE_RATE_COLUMNS:
            return f"argMax({metric}_rate, executed_at)"

        # Fallback: (max - min) / time_delta with div/0 safety
        if self.target_table == "performance":
            metric_ref = f"metric_values[indexOf(metric_names, '{metric}')]"
            self._where_extras.append(f"has(metric_names, '{metric}')")
        else:
            metric_ref = metric

        time_delta = "(toUnixTimestamp(max(executed_at)) - toUnixTimestamp(min(executed_at)))"
        value_delta = f"(max({metric_ref}) - min({metric_ref}))"
        return f"if({time_delta} = 0, nan, {value_delta} / {time_delta})"

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

        group_by_str = ", ".join(group_by + ["config_value"])
        sql = (
            f"SELECT {', '.join(select_cols)} "
            f"FROM config_latest FINAL "
            f"WHERE {' AND '.join(where_parts)} "
            f"GROUP BY {group_by_str}"
        )
        return CompiledQuery(sql=sql, params=self.params, threshold_params=[])

    def _build_config_where(self, node: ASTNode, parts: list[str]) -> None:
        if isinstance(node, Comparison) and isinstance(node.left, str):
            if node.op not in _VALID_COMPARE_OPS:
                raise ParseError(f"Invalid comparison operator: {node.op!r}")
            ch_op = "=" if node.op == "==" else node.op
            key = _assert_safe_identifier(node.left, "config_key")
            param_key_name = f"_str_val_{self._str_idx}"
            parts.append(f"config_key = '{key}'")
            parts.append(f"config_value {ch_op} {{{param_key_name}:String}}")
            self.params[param_key_name] = str(node.right)
            self._str_idx += 1
        elif isinstance(node, InList):
            key = _assert_safe_identifier(node.identifier, "config_key")
            param_keys = []
            for i, val in enumerate(node.values):
                pk = f"_in_val_{self._str_idx}_{i}"
                self.params[pk] = val
                param_keys.append(f"{{{pk}:String}}")
            op_str = "NOT IN" if node.negated else "IN"
            parts.append(f"config_key = '{key}'")
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


def _arith_to_string(node: ArithNode) -> str:
    """Convert an ArithNode back to a DSL expression string."""
    if isinstance(node, AggCall):
        return f"{node.func}({node.metric})"
    elif isinstance(node, NumericLiteral):
        v = node.value
        return str(int(v)) if v == int(v) else str(v)
    elif isinstance(node, ArithOp):
        left = _arith_to_string(node.left)
        right = _arith_to_string(node.right)
        return f"{left} {node.op} {right}"
    return str(node)


def _threshold_ref_to_string(ref: ThresholdRef) -> str:
    """Convert a ThresholdRef back to a DSL expression string."""
    if ref.is_named:
        return ref.name
    # Inline value — output the number
    v = ref.inline_value
    return str(int(v)) if v == int(v) else str(v)


def _ast_to_string(node: ASTNode) -> str:
    """Convert an AST node back to a DSL expression string."""
    if isinstance(node, Comparison):
        if isinstance(node.left, str):
            left_str = node.left
        else:
            left_str = _arith_to_string(node.left)
        if isinstance(node.right, ThresholdRef):
            right_str = _threshold_ref_to_string(node.right)
        elif isinstance(node.right, str):
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
