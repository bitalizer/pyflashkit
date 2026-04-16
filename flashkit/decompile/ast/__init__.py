"""Typed AST for AS3 source produced by the decompiler.

The AST is the intermediate representation between the CFG-based
structurer (Phase 6) and the printed source. Structuring builds
statement nodes out of per-block expression trees produced by the
stack simulator; pattern-matching passes (Phase 8) rewrite the AST
into idiomatic AS3; the printer serialises it.

All nodes are dataclasses. Equality/hashing is by value. Fields are
public so pattern passes can build new nodes or mutate in place — we
deliberately don't make nodes immutable.
"""

from .nodes import (
    Node,
    Statement, Expression,
    # statements
    BlockStmt, IfStmt, WhileStmt, DoWhileStmt, ForStmt, ForInStmt,
    ForEachStmt, SwitchStmt, SwitchCase, TryStmt, CatchClause,
    ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt, LabeledStmt,
    ExpressionStmt, VarDeclStmt,
    # expressions
    Literal, Identifier, MemberAccess, MethodCall, NewExpr,
    BinaryOp, UnaryOp, TernaryOp, AssignExpr, CompoundAssignExpr,
    IndexAccess, CastExpr, IsExpr, AsExpr, FunctionExpr,
    ArrayLiteral, ObjectLiteral, ObjectProperty,
    TypeofExpr, DeleteExpr, InExpr,
)
from .printer import AstPrinter

__all__ = [
    "Node", "Statement", "Expression",
    "AstPrinter",
    "BlockStmt", "IfStmt", "WhileStmt", "DoWhileStmt", "ForStmt",
    "ForInStmt", "ForEachStmt", "SwitchStmt", "SwitchCase", "TryStmt",
    "CatchClause", "ReturnStmt", "ThrowStmt", "BreakStmt",
    "ContinueStmt", "LabeledStmt", "ExpressionStmt", "VarDeclStmt",
    "Literal", "Identifier", "MemberAccess", "MethodCall", "NewExpr",
    "BinaryOp", "UnaryOp", "TernaryOp", "AssignExpr",
    "CompoundAssignExpr", "IndexAccess", "CastExpr", "IsExpr",
    "AsExpr", "FunctionExpr", "ArrayLiteral", "ObjectLiteral",
    "ObjectProperty", "TypeofExpr", "DeleteExpr", "InExpr",
]
