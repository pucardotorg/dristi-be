"""Sample rules shared by the test_rules_* modules."""

import json

from apps.core.models import BusinessRule

COURT_FEE_INPUT = {
    "type": "object",
    "properties": {
        "case_value": {"type": "number"},
        "case_type": {"type": "string", "enum": ["civil", "criminal"]},
    },
    "required": ["case_value", "case_type"],
    "additionalProperties": False,
}
COURT_FEE_OUTPUT = {
    "type": "object",
    "properties": {"fee": {"type": "number"}, "currency": {"type": "string"}},
    "required": ["fee"],
    "additionalProperties": False,
}
COURT_FEE_EXPRESSION = (
    'case_value > 100000 ? {"fee": 500, "currency": "INR"} : {"fee": 100, "currency": "INR"}'
)

ELIGIBILITY_OUTPUT = {
    "type": "object",
    "properties": {"eligible": {"type": "boolean"}},
    "required": ["eligible"],
    "additionalProperties": False,
}


def jdm(nodes, edges):
    """Return a JDM document as stored JSON text."""
    return json.dumps({"nodes": nodes, "edges": edges})


def edge(source, target):
    return {"id": f"{source}-{target}", "sourceId": source, "targetId": target, "type": "edge"}


INPUT_NODE = {"id": "in", "type": "inputNode", "name": "Request"}
OUTPUT_NODE = {"id": "out", "type": "outputNode", "name": "Response"}


def table_node(node_id="table", name="Eligibility"):
    """Civil cases above 1,00,000 are eligible; everything else is not."""
    return {
        "id": node_id,
        "type": "decisionTableNode",
        "name": name,
        "content": {
            "hitPolicy": "first",
            "inputs": [
                {"id": "value", "name": "Case value", "field": "case_value"},
                {"id": "type", "name": "Case type", "field": "case_type"},
            ],
            "outputs": [{"id": "eligible", "name": "Eligible", "field": "eligible"}],
            "rules": [
                {"_id": "r1", "value": "> 100000", "type": '"civil"', "eligible": "true"},
                {"_id": "r2", "value": "", "type": "", "eligible": "false"},
            ],
        },
    }


def expression_node(expressions, node_id="expr", name="Compute"):
    return {
        "id": node_id,
        "type": "expressionNode",
        "name": name,
        "content": {
            "expressions": [
                {"id": f"e{i}", "key": key, "value": value}
                for i, (key, value) in enumerate(expressions.items())
            ]
        },
    }


def linear_graph(*middle):
    """input -> middle nodes in order -> output."""
    nodes = [INPUT_NODE, *middle, OUTPUT_NODE]
    edges = [edge(a["id"], b["id"]) for a, b in zip(nodes, nodes[1:], strict=False)]
    return jdm(nodes, edges)


ELIGIBILITY_GRAPH = linear_graph(table_node())


def make_rule(**overrides):
    """Create and save a valid rule-engine court-fee rule, with overrides."""
    fields = {
        "code": "COURT_FEE_CALCULATION",
        "name": "Court fee calculation",
        "engine": BusinessRule.RuleEngineType.RULE_ENGINE,
        "rule_expression": COURT_FEE_EXPRESSION,
        "rule_input_schema": COURT_FEE_INPUT,
        "rule_output_schema": COURT_FEE_OUTPUT,
    }
    fields.update(overrides)
    return BusinessRule.objects.create(**fields)


def make_gorules_rule(**overrides):
    """Create and save a valid GoRules eligibility rule, with overrides."""
    fields = {
        "code": "SUMMONS_GENERATION_ELIGIBILITY",
        "name": "Summons generation eligibility",
        "engine": BusinessRule.RuleEngineType.GORULES,
        "rule_expression": ELIGIBILITY_GRAPH,
        "rule_input_schema": COURT_FEE_INPUT,
        "rule_output_schema": ELIGIBILITY_OUTPUT,
    }
    fields.update(overrides)
    return make_rule(**fields)
