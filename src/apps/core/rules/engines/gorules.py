"""GoRules / zen-engine adapter (spec 0019 #4.5).

The JDM graph is evaluated in-process by the official ZEN binding. The engine
is created without a loader, so a stored graph cannot pull in other graphs or
perform I/O.

Timeout note (spec 0019 #11.5): the synchronous ``ZenDecision.evaluate`` holds
the GIL for the whole Rust call, which would starve the base class's guard
thread. Evaluation therefore awaits ``async_evaluate``, which runs on ZEN's
own Rust thread pool with the GIL released, so the guard returns a
RuleEvaluationError on time. The Rust computation itself cannot be cancelled:
a timed-out evaluation runs to completion in the background and its result is
discarded.
"""

import asyncio
import json
import re
from collections import defaultdict

import zen

from apps.core.models import BusinessRule

from ..exceptions import RuleDefinitionError, RuleEvaluationError
from .base import RuleEngine

SUPPORTED_NODE_TYPES = frozenset(
    {"inputNode", "outputNode", "decisionTableNode", "expressionNode", "switchNode"}
)
# Why the remaining ZEN node types are refused at save time.
UNSUPPORTED_NODE_REASONS = {
    "decisionNode": "cross-graph references need a loader, which is disabled",
    "functionNode": "JavaScript function nodes have an undeterminable input surface",
    "customNode": "custom nodes need a host-registered handler",
}


class _UndecidableError(Exception):
    """The input surface of an expression cannot be determined statically."""


_KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false", "null"})
_IDENTIFIER = re.compile(r"[A-Za-z_$#][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?")
_OPERATOR_CHARS = frozenset("+-*/%^<>=!?:|&")


class _IdentifierScanner:
    """Collect the free variables a ZEN expression reads.

    ZEN does not expose its parser, so this walks the token stream. It skips
    string literals, member names (``a.b`` reads ``a``), function names
    (``len(...)``), object-literal keys, keywords, ``$`` (the current column
    in a table cell) and ``#`` (the closure argument). Anything it cannot
    classify raises ``_UndecidableError`` so that the result is never silently
    incomplete.
    """

    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.names = set()

    def run(self):
        self._scan()
        return self.names

    def _scan(self, stop=None):
        source = self.source
        prev = None
        brackets = []
        while self.pos < len(source):
            char = source[self.pos]
            if char.isspace():
                self.pos += 1
                continue
            if stop is not None and char == stop and not brackets:
                self.pos += 1
                return
            if char in "'\"":
                self._skip_string(char)
                prev = "literal"
            elif char == "`":
                self._scan_template()
                prev = "literal"
            elif char.isdigit():
                self.pos = _NUMBER.match(source, self.pos).end()
                prev = "literal"
            elif char == ".":
                prev = ".." if source.startswith("..", self.pos) else "."
                self.pos += len(prev)
            elif match := _IDENTIFIER.match(source, self.pos):
                self.pos = match.end()
                self._classify(match.group(), prev, brackets)
                prev = "identifier"
            elif char in "([{":
                brackets.append(char)
                prev = char
                self.pos += 1
            elif char in ")]}":
                if not brackets:
                    raise _UndecidableError(f"unbalanced {char!r} in {source!r}")
                brackets.pop()
                prev = char
                self.pos += 1
            elif char == ",":
                prev = ","
                self.pos += 1
            elif char in _OPERATOR_CHARS:
                prev = "operator"
                self.pos += 1
            else:
                raise _UndecidableError(f"unexpected character {char!r} in {source!r}")
        if stop is not None:
            raise _UndecidableError(f"unterminated template interpolation in {source!r}")
        if brackets:
            raise _UndecidableError(f"unbalanced brackets in {source!r}")

    def _classify(self, name, prev, brackets):
        following = self._next_char()
        if prev == ".":
            return  # member access: only the root of a path is an input
        if name in ("$", "#"):
            return  # current table column / closure argument
        if name[0] in "$#":
            # $root, $nodes and friends read the whole context or other nodes.
            raise _UndecidableError(f"{name!r} reads beyond named inputs")
        if following == "(" or name in _KEYWORDS:
            return
        if following == ":" and prev in ("{", ",") and brackets and brackets[-1] == "{":
            return  # object-literal key
        self.names.add(name)

    def _next_char(self):
        pos = self.pos
        while pos < len(self.source) and self.source[pos].isspace():
            pos += 1
        return self.source[pos] if pos < len(self.source) else ""

    def _skip_string(self, quote):
        self.pos += 1
        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            self.pos += 1
            if char == quote:
                return
        raise _UndecidableError(f"unterminated string in {self.source!r}")

    def _scan_template(self):
        self.pos += 1
        while self.pos < len(self.source):
            if self.source[self.pos] == "\\":
                self.pos += 2
            elif self.source[self.pos] == "`":
                self.pos += 1
                return
            elif self.source.startswith("${", self.pos):
                self.pos += 2
                self._scan(stop="}")
            else:
                self.pos += 1
        raise _UndecidableError(f"unterminated template in {self.source!r}")


def _identifiers(source):
    """Return the free variables read by one ZEN expression or table cell."""
    if not isinstance(source, str):
        raise _UndecidableError(f"expected an expression string, got {type(source).__name__}")
    return _IdentifierScanner(source).run()


def _root(path):
    """Return the top-level key of an output path such as ``fee.amount``."""
    return re.split(r"[.\[]", path, maxsplit=1)[0]


async def _evaluate_async(decision, payload, options):
    return await decision.async_evaluate(payload, options)


class GoRulesRuleEngine(RuleEngine):
    """Evaluates GoRules JDM documents stored as JSON text."""

    engine = BusinessRule.RuleEngineType.GORULES

    def __init__(self):
        super().__init__()
        # No loader: see the module docstring and spec 0019 #4.5.
        self._engine = zen.ZenEngine()

    def validate(self, rule_expression, rule_input_schema=None):
        self._decision(rule_expression)

    def referenced_inputs(self, rule_expression, rule_input_schema=None):
        graph = self._load(rule_expression)
        reads, produces = {}, {}
        for node in graph["nodes"]:
            try:
                reads[node["id"]], produces[node["id"]] = self._node_io(node)
            except _UndecidableError as exc:
                raise RuleDefinitionError(
                    f"Cannot determine the inputs read by node {node.get('name') or node['id']!r}: {exc}"
                ) from exc

        parents = defaultdict(set)
        for edge in graph["edges"]:
            parents[edge["targetId"]].add(edge["sourceId"])

        referenced = set()
        for node_id, names in reads.items():
            # A name produced by an upstream node is that node's output, not an
            # input. Anything else counts as an input (a conservative superset).
            upstream = set()
            for ancestor in self._ancestors(node_id, parents):
                upstream |= produces.get(ancestor, set())
            referenced |= names - upstream
        return referenced

    def evaluate(self, rule_expression, payload, rule_input_schema=None, *, cache_key=None):
        decision = self._memoized(cache_key, lambda: self._decision(rule_expression))
        # Only "result" crosses the abstraction; performance/trace stay behind.
        return self._run(decision, payload, trace=False)["result"]

    def trace(self, rule_expression, payload, rule_input_schema=None):
        return self._run(self._decision(rule_expression), payload, trace=True).get("trace")

    @staticmethod
    def _run(decision, payload, *, trace):
        try:
            return asyncio.run(_evaluate_async(decision, payload, {"trace": trace}))
        except Exception as exc:
            raise RuleEvaluationError(f"Evaluation failed: {exc}") from exc

    @staticmethod
    def _load(rule_expression):
        """Parse the JDM JSON and enforce the supported graph shape."""
        try:
            graph = json.loads(rule_expression)
        except (TypeError, ValueError) as exc:
            raise RuleDefinitionError(f"JDM document is not valid JSON: {exc}") from exc
        if not isinstance(graph, dict):
            raise RuleDefinitionError("JDM document must be a JSON object.")
        nodes, edges = graph.get("nodes"), graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise RuleDefinitionError('JDM document must have "nodes" and "edges" arrays.')
        for node in nodes:
            if not isinstance(node, dict) or "id" not in node or "type" not in node:
                raise RuleDefinitionError('Every JDM node must be an object with "id" and "type".')
            node_type = node["type"]
            if node_type not in SUPPORTED_NODE_TYPES:
                reason = UNSUPPORTED_NODE_REASONS.get(node_type, "unknown node type")
                raise RuleDefinitionError(f"Node type {node_type!r} is not supported: {reason}.")
        for edge in edges:
            if not isinstance(edge, dict) or "sourceId" not in edge or "targetId" not in edge:
                raise RuleDefinitionError('Every JDM edge must have "sourceId" and "targetId".')
        return graph

    def _decision(self, rule_expression):
        """Compile the graph, raising RuleDefinitionError for anything ZEN refuses."""
        graph = self._load(rule_expression)
        for node in graph["nodes"]:
            for source in self._standard_expressions(node):
                problem = zen.validate_expression(source)
                if problem:
                    raise RuleDefinitionError(
                        f"Node {node.get('name') or node['id']!r}: invalid expression "
                        f"{source!r} ({problem['type']}: {problem['source']})."
                    )
        try:
            decision = self._engine.create_decision(rule_expression)
            decision.validate()
        except Exception as exc:
            raise RuleDefinitionError(f"ZEN refused the decision graph: {exc}") from exc
        return decision

    @staticmethod
    def _standard_expressions(node):
        """Yield the full (non-unary) expressions in a node, for syntax checks.

        Decision-table cells are left to ZEN and the dry run: ZEN accepts cell
        forms (such as comma lists) that its standalone validators reject.
        """
        content = node.get("content") or {}
        if node["type"] == "expressionNode":
            for expression in content.get("expressions") or []:
                yield expression.get("value", "")
        elif node["type"] == "switchNode":
            for statement in content.get("statements") or []:
                if statement.get("condition"):
                    yield statement["condition"]

    @staticmethod
    def _node_io(node):
        """Return ``(names read, top-level keys produced)`` for one node."""
        content = node.get("content") or {}
        if content.get("inputField"):
            raise _UndecidableError("inputField rescopes the node's input")
        node_type = node["type"]
        reads, produces = set(), set()

        if node_type == "expressionNode":
            for expression in content.get("expressions") or []:
                reads |= _identifiers(expression.get("value", ""))
                produces.add(_root(expression.get("key", "")))
        elif node_type == "switchNode":
            for statement in content.get("statements") or []:
                reads |= _identifiers(statement.get("condition") or "")
        elif node_type == "decisionTableNode":
            inputs = content.get("inputs") or []
            outputs = content.get("outputs") or []
            for column in inputs:
                reads |= _identifiers(column.get("field") or "")
            for column in outputs:
                produces.add(_root(column.get("field", "")))
            column_ids = [column["id"] for column in inputs + outputs]
            for row in content.get("rules") or []:
                for column_id in column_ids:
                    reads |= _identifiers(row.get(column_id) or "")

        if content.get("outputPath"):
            produces = {_root(content["outputPath"])}
        produces.discard("")
        return reads, produces

    @staticmethod
    def _ancestors(node_id, parents):
        seen, stack = set(), list(parents.get(node_id, ()))
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(parents.get(current, ()))
        return seen
