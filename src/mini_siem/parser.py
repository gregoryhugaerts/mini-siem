"""SQL Query Parser and Generator Module

This module provides functionality for parsing and generating SQL queries based on a custom grammar.
It uses the Lark library for parsing and the SQLModel library for generating SQL queries.

The module defines a grammar for parsing queries, which can be used to filter events based on various attributes.
It also provides functions for generating SQL queries from parsed query trees.

Classes:
    None

Functions:
    generate_event_sql_query(tree: lark.Tree) -> SelectOfScalar:
        Generates a SQL query from a parsed query tree.
    _handle_query(query):
        Handles a query node in the parsed query tree.
    _handle_filter(filter) -> bool:
        Handles a filter node in the parsed query tree.

Variables:
    query_grammar (str):
        The grammar for parsing queries.
    parser (lark.Lark):
        The parser instance for the query grammar.
"""

import operator
from typing import cast

import lark
from sqlalchemy import ColumnElement
from sqlmodel import and_, or_, select
from sqlmodel.sql._expression_select_cls import SelectOfScalar

from mini_siem.models import Event

query_grammar = r"""
    start: query
    ?query: filter ((AND | OR) filter)*
    filter: attr cmp value | nested_attr cmp value
    cmp: ">" | "<" | "=" |  "<=" | ">=" | "!=" | "in"
    attr: "id" | "timestamp" | "source"
    nested_attr: "data" ( "." key )*
    key: CNAME
    value: SIGNED_NUMBER | ESCAPED_STRING | VARIABLE
    AND: " and " 
    OR: " or "
    %import common.CNAME
    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    VARIABLE: /[a-zA-Z_][a-zA-Z_0-9]*/
    NUMBER: /\d+/
"""

parser = lark.Lark(query_grammar, start="start", keep_all_tokens=True)


def generate_event_sql_query(tree: lark.Tree) -> SelectOfScalar:
    """Generates a SQL query from a parsed query tree.

    Args:
        tree (lark.Tree): The parsed query tree

    Returns:
        SelectOfScalar: The generated SQL query

    Example:
        >>> query_tree = parser.parse("id = 1 and timestamp > 1643723400")
        >>> sql_query = generate_event_sql_query(query_tree)
        >>> print(sql_query)
        SELECT * FROM events WHERE events.id = 1 AND events.timestamp > 1643723400

    """
    query = select(Event)
    clauses = []
    for child in tree.children:
        if child.data == "filter":
            clauses.append(_handle_filter(child))
        elif child.data == "query":
            clauses.append(_handle_query(child))
    if clauses:
        query = query.where(*clauses)
    return query


def _handle_query(query: lark.Tree) -> ColumnElement[bool]:
    """Handles a query node in the parsed query tree.

    This function takes a query node and recursively processes its children to generate a SQL filter clause.
    It supports AND and OR operators and can handle nested filters.

    Args:
        query (lark.Tree): The query node

    Returns:
        ColumnElement[bool]: The resulting filter clause

    Raises:
        ValueError: If an unexpected operator is encountered

    """
    left_filter = _handle_filter(query.children[0])

    # Start iterating from the first operator (at index 1)
    i = 1
    while i < len(query.children):
        op: str = cast(lark.Token, query.children[i]).type
        right_filter = _handle_filter(query.children[i + 1])

        if op == "OR":
            left_filter = or_(left_filter, right_filter)
        elif op == "AND":
            left_filter = and_(left_filter, right_filter)
        else:
            raise ValueError("Unexpected Clause; expected AND or OR, got %s" % op)

        # Move to the next operator and filter pair
        i += 2

    return cast(ColumnElement[bool], left_filter)


def _handle_filter(filter: lark.Tree) -> bool:
    """Handles a filter node in the parsed query tree.

    Args:
        filter (lark.Tree): The filter node

    Returns:
        bool: The resulting filter clause

    """
    attr_or_nested_attr = filter.children[0]
    cmp: str = cast(lark.Token, filter.children[1].children[0]).value
    value = cast(lark.Token, filter.children[2].children[0]).value
    ops = {
        ">": operator.gt,
        "<": operator.lt,
        "=": operator.eq,
        ">=": operator.ge,
        "<=": operator.le,
        "!=": operator.ne,
        "in": operator.contains,
    }
    if attr_or_nested_attr.data == "attr":
        attr = cast(lark.Token, attr_or_nested_attr.children[0]).value
        return ops[cmp](getattr(Event, attr), value)
    if attr_or_nested_attr.data == "nested_attr":
        nested_attr_path = []
        for filter in attr_or_nested_attr.children[1:]:
            if isinstance(filter, lark.Tree):
                nested_attr_path.append(cast(lark.Token, filter.children[0]).value)
            elif filter.type == "KEY":
                nested_attr_path.append(filter.value)
        attr = Event.data
        for path in nested_attr_path:
            attr = attr[path]
        return ops[cmp](attr, value)
    return False
