"""SQL Query Parser and Generator Module

This module provides functionality for parsing and generating SQL queries based on a custom grammar.
It uses the Lark library for parsing and the SQLModel library for generating SQL queries.

The module defines a grammar for parsing queries, which can be used to filter events based on various attributes.
It also provides functions for generating SQL queries from parsed query trees.

Supports:
    - Comparisons: >, <, =, <=, >=, !=, in, ~ (substring match), !~ (negated substring match)
    - Grouping via parentheses: (a and b) or c
    - Negation: not a, not (a or b)
    - Whitespace tolerant: "id = 1 and timestamp > 5" and "id=1 and timestamp>5"
      both parse identically -- the original grammar only tolerated the
      latter, which was undocumented and not obvious from the code alone.

Classes:
    None

Functions:
    generate_event_sql_query(tree: lark.Tree) -> SelectOfScalar:
        Generates a SQL query from a parsed query tree.
    _eval(node) -> ColumnElement[bool]:
        Recursively evaluates a parsed query tree node (filter, and_expr,
        or_expr, not_expr, or a parenthesized atom) into a SQLAlchemy
        boolean expression.
    _handle_filter(filter) -> ColumnElement[bool]:
        Handles a filter node in the parsed query tree.
    _parse_value(value_node):
        Converts a parsed `value` node into a real Python value.

Variables:
    query_grammar (str):
        The grammar for parsing queries.
    parser (lark.Lark):
        The parser instance for the query grammar.
"""

import operator
from typing import cast

import lark
from sqlalchemy import ColumnElement, not_ as sql_not
from sqlmodel import and_, or_, select
from sqlmodel.sql._expression_select_cls import SelectOfScalar

from mini_siem.models import Event

query_grammar = r"""
    start: query
    ?query: or_expr
    ?or_expr: and_expr (OR and_expr)*
    ?and_expr: not_expr (AND not_expr)*
    ?not_expr: NOT not_expr
             | atom
    ?atom: filter
         | "(" query ")"
    filter: attr cmp value | nested_attr cmp value
    cmp: ">" | "<" | "=" |  "<=" | ">=" | "!=" | "in" | "~" | "!~"
    attr: "id" | "timestamp" | "source"
    nested_attr: "data" ( "." key )*
    key: CNAME
    value: SIGNED_NUMBER | ESCAPED_STRING | VARIABLE | list
    list: "[" value ("," value)* "]"
    AND.2: "and"
    OR.2: "or"
    NOT.2: "not"
    %import common.CNAME
    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %ignore WS
    VARIABLE: /[a-zA-Z_][a-zA-Z_0-9]*/
    NUMBER: /\d+/
"""

parser = lark.Lark(query_grammar, start="start", keep_all_tokens=True)

# `in` needs a real Python list and SQLAlchemy's own .in_(), not a
# scalar operator -- kept separate from _SCALAR_OPS below rather than
# forced into the same dispatch table.
_SPECIAL_OPS = {"in"}

_SCALAR_OPS = {
    ">": operator.gt,
    "<": operator.lt,
    "=": operator.eq,
    ">=": operator.ge,
    "<=": operator.le,
    "!=": operator.ne,
    # Substring match -- compiles to LIKE '%value%', works on SQLite
    # with no extra setup. True regex would need a REGEXP function
    # registered on the connection (SQLite has none built in); worth
    # adding later if substring matching proves insufficient.
    "~": lambda col, val: col.contains(val),
    "!~": lambda col, val: ~col.contains(val),
}


def generate_event_sql_query(tree: lark.Tree) -> SelectOfScalar:
    """Generates a SQL query from a parsed query tree.

    Args:
        tree (lark.Tree): The parsed query tree

    Returns:
        SelectOfScalar: The generated SQL query

    Example:
        >>> query_tree = parser.parse("id = 1 and timestamp > 1643723400")
        >>> sql_query = generate_event_sql_query(query_tree)

    """
    query = select(Event)
    clause = _eval(tree.children[0])
    if clause is not None:
        query = query.where(clause)
    return query


def _eval(node) -> ColumnElement[bool]:
    """Recursively evaluates any node in the parsed query tree.

    Replaces the original _handle_query/_handle_filter split with a
    single recursive dispatcher, since grouping and negation mean a
    node can now be a filter, an and_expr/or_expr chain, a negated
    sub-expression, or a parenthesized atom -- more shapes than the
    original flat two-branch design accounted for.

    Args:
        node (lark.Tree): any node produced by the grammar above

    Returns:
        ColumnElement[bool]: the resulting SQLAlchemy boolean expression
    """
    if node.data == "filter":
        return _handle_filter(node)

    if node.data == "not_expr":
        # children: [NOT token, <nested not_expr or atom>]
        inner = node.children[1]
        return sql_not(_eval(inner))

    if node.data == "atom":
        # children may include literal "(" / ")" tokens (kept due to
        # keep_all_tokens=True) alongside the real nested query --
        # filter down to the one Tree child rather than assuming a
        # fixed position.
        inner = next(c for c in node.children if isinstance(c, lark.Tree))
        return _eval(inner)

    if node.data in ("and_expr", "or_expr"):
        # children alternate: filter/expr, AND-or-OR token, filter/expr, ...
        result = _eval(node.children[0])
        i = 1
        while i < len(node.children):
            op_token = cast(lark.Token, node.children[i])
            right = _eval(node.children[i + 1])
            if op_token.type == "AND":
                result = and_(result, right)
            elif op_token.type == "OR":
                result = or_(result, right)
            else:
                raise ValueError(
                    "Unexpected token; expected AND or OR, got %s" % op_token.type
                )
            i += 2
        return result

    raise ValueError("Unexpected node type: %s" % node.data)


def _parse_value(value_node: lark.Tree):
    """Converts a parsed `value` node into a real Python value.

    Handles scalars (numbers, quoted strings, bare identifiers) and
    list literals for the `in` operator. String tokens have their
    surrounding quotes stripped -- ESCAPED_STRING's raw token text
    includes the quote characters, which previously meant every
    string comparison was silently comparing against a quoted literal
    rather than the intended bare value.

    Args:
        value_node (lark.Tree): the `value` rule's parse node

    Returns:
        str | int | float | list: the corresponding Python value
    """
    child = value_node.children[0]

    if isinstance(child, lark.Tree) and child.data == "list":
        # list children include literal "[" / "]" / "," tokens due to
        # keep_all_tokens=True -- only recurse into actual `value` subtrees.
        return [
            _parse_value(item)
            for item in child.children
            if isinstance(item, lark.Tree) and item.data == "value"
        ]

    token = cast(lark.Token, child)
    if token.type == "ESCAPED_STRING":
        return token.value[1:-1]  # strip the surrounding quotes
    if token.type == "SIGNED_NUMBER":
        return float(token.value) if "." in token.value else int(token.value)
    return token.value  # VARIABLE -- bare identifier, left as-is


def _handle_filter(filter: lark.Tree) -> ColumnElement[bool]:
    """Handles a filter node in the parsed query tree.

    Args:
        filter (lark.Tree): The filter node

    Returns:
        ColumnElement[bool]: The resulting filter clause

    """
    attr_or_nested_attr = filter.children[0]
    cmp: str = cast(lark.Token, filter.children[1].children[0]).value
    value = _parse_value(filter.children[2])

    if attr_or_nested_attr.data == "attr":
        attr_name = cast(lark.Token, attr_or_nested_attr.children[0]).value
        column = getattr(Event, attr_name)
    elif attr_or_nested_attr.data == "nested_attr":
        nested_attr_path = []
        for part in attr_or_nested_attr.children[1:]:
            if isinstance(part, lark.Tree):
                nested_attr_path.append(cast(lark.Token, part.children[0]).value)
            elif part.type == "KEY":
                nested_attr_path.append(part.value)
        column = Event.data
        for path in nested_attr_path:
            column = column[path]
    else:
        raise ValueError("Unexpected filter target: %s" % attr_or_nested_attr.data)

    if cmp in _SPECIAL_OPS:
        if not isinstance(value, list):
            raise ValueError("`in` requires a list value, e.g. field in [1, 2, 3]")
        return column.in_(value)

    return _SCALAR_OPS[cmp](column, value)
