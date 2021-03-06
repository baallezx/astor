# -*- coding: utf-8 -*-
"""
This module converts an AST into Python source code.

Original code copyright (c) 2008 by Armin Ronacher and
is distributed under the BSD license.

It was derived from a modified version found here:

    https://gist.github.com/1250562

"""

import ast

from astor.misc import ExplicitNodeVisitor
from astor.misc import get_boolop, get_binop, get_cmpop, get_unaryop


def to_source(node, indent_with=' ' * 4, add_line_information=False):
    """This function can convert a node tree back into python sourcecode.
    This is useful for debugging purposes, especially if you're dealing with
    custom asts not generated by python itself.

    It could be that the sourcecode is evaluable when the AST itself is not
    compilable / evaluable.  The reason for this is that the AST contains some
    more data than regular sourcecode does, which is dropped during
    conversion.

    Each level of indentation is replaced with `indent_with`.  Per default this
    parameter is equal to four spaces as suggested by PEP 8, but it might be
    adjusted to match the application's styleguide.

    If `add_line_information` is set to `True` comments for the line numbers
    of the nodes are added to the output.  This can be used to spot wrong line
    number information of statement nodes.

    """
    generator = SourceGenerator(indent_with, add_line_information)
    generator.visit(node)
    return ''.join(str(s) for s in generator.result)


def enclose(enclosure):
    def decorator(func):
        def newfunc(self, node):
            self.write(enclosure[0])
            func(self, node)
            self.write(enclosure[-1])
        return newfunc
    return decorator


class SourceGenerator(ExplicitNodeVisitor):
    """This visitor is able to transform a well formed syntax tree into Python
    sourcecode.

    For more details have a look at the docstring of the `node_to_source`
    function.

    """

    def __init__(self, indent_with, add_line_information=False):
        self.result = []
        self.indent_with = indent_with
        self.add_line_information = add_line_information
        self.indentation = 0
        self.new_lines = 0

    def write(self, *params):
        for item in params:
            if isinstance(item, ast.AST):
                self.visit(item)
            elif hasattr(item, '__call__'):
                item()
            elif item == '\n':
                self.newline()
            else:
                if self.new_lines:
                    if self.result:
                        self.result.append('\n' * self.new_lines)
                    self.result.append(self.indent_with * self.indentation)
                    self.new_lines = 0
                self.result.append(item)

    def conditional_write(self, *stuff):
        if stuff[-1] is not None:
            self.write(*stuff)

    def newline(self, node=None, extra=0):
        self.new_lines = max(self.new_lines, 1 + extra)
        if node is not None and self.add_line_information:
            self.write('# line: %s' % node.lineno)
            self.new_lines = 1

    def body(self, statements):
        self.indentation += 1
        for stmt in statements:
            self.visit(stmt)
        self.indentation -= 1

    def else_body(self, elsewhat):
        if elsewhat:
            self.write('\n', 'else:')
            self.body(elsewhat)

    def body_or_else(self, node):
        self.body(node.body)
        self.else_body(node.orelse)

    def signature(self, node):
        want_comma = []

        def write_comma():
            if want_comma:
                self.write(', ')
            else:
                want_comma.append(True)

        def loop_args(args, defaults):
            padding = [None] * (len(args) - len(defaults))
            for arg, default in zip(args, padding + defaults):
                self.write(write_comma, arg)
                self.conditional_write('=', default)

        loop_args(node.args, node.defaults)
        self.conditional_write(write_comma, '*', node.vararg)
        self.conditional_write(write_comma, '**', node.kwarg)

        kwonlyargs = getattr(node, 'kwonlyargs', None)
        if kwonlyargs:
            if node.vararg is None:
                self.write(write_comma, '*')
            loop_args(kwonlyargs, node.kw_defaults)

    def statement(self, node, *params, **kw):
        self.newline(node)
        self.write(*params)

    def decorators(self, node, extra):
        self.newline(extra=extra)
        for decorator in node.decorator_list:
            self.statement(decorator, '@', decorator)

    def comma_list(self, items, trailing=False):
        for idx, item in enumerate(items):
            if idx:
                self.write(', ')
            self.visit(item)
        if trailing:
            self.write(',')

    # Statements

    def visit_Assign(self, node):
        self.newline(node)
        for target in node.targets:
            self.write(target, ' = ')
        self.visit(node.value)

    def visit_AugAssign(self, node):
        self.statement(node, node.target, get_binop(node.op, ' %s= '),
                       node.value)

    def visit_ImportFrom(self, node):
        if node.module:
            self.statement(node, 'from ', node.level * '.',
                           node.module, ' import ')
        else:
            self.statement(node, 'from ', node.level * '. import ')
        self.comma_list(node.names)

    def visit_Import(self, node):
        self.statement(node, 'import ')
        self.comma_list(node.names)

    def visit_Expr(self, node):
        self.statement(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.decorators(node, 1)
        self.statement(node, 'def %s(' % node.name)
        self.signature(node.args)
        self.write(')')
        if getattr(node, 'returns', None) is not None:
            self.write(' ->', node.returns)
        self.write(':')
        self.body(node.body)

    def visit_ClassDef(self, node):
        have_args = []

        def paren_or_comma():
            if have_args:
                self.write(', ')
            else:
                have_args.append(True)
                self.write('(')

        self.decorators(node, 2)
        self.statement(node, 'class %s' % node.name)
        for base in node.bases:
            self.write(paren_or_comma, base)
        # XXX: the if here is used to keep this module compatible
        #      with python 2.6.
        if hasattr(node, 'keywords'):
            for keyword in node.keywords:
                self.write(paren_or_comma, keyword.arg, '=', keyword.value)
            self.conditional_write(paren_or_comma, '*', node.starargs)
            self.conditional_write(paren_or_comma, '**', node.kwargs)
        self.write(have_args and '):' or ':')
        self.body(node.body)

    def visit_If(self, node):
        self.statement(node, 'if ', node.test, ':')
        self.body(node.body)
        while True:
            else_ = node.orelse
            if len(else_) == 1 and isinstance(else_[0], ast.If):
                node = else_[0]
                self.write('\n', 'elif ', node.test, ':')
                self.body(node.body)
            else:
                self.else_body(else_)
                break

    def visit_For(self, node):
        self.statement(node, 'for ', node.target, ' in ', node.iter, ':')
        self.body_or_else(node)

    def visit_While(self, node):
        self.statement(node, 'while ', node.test, ':')
        self.body_or_else(node)

    def visit_With(self, node):
        if hasattr(node, "context_expr"):  # Python < 3.3
            self.statement(node, 'with ', node.context_expr)
            self.conditional_write(' as ', node.optional_vars)
            self.write(':')
        else:                              # Python >= 3.3
            self.statement(node, 'with ')
            count = 0
            for item in node.items:
                if count > 0:
                    self.write(" , ")
                self.visit(item)
                count += 1
            self.write(':')
        self.body(node.body)

    # new for Python 3.3
    def visit_withitem(self, node):
        self.write(node.context_expr)
        self.conditional_write(' as ', node.optional_vars)

    def visit_Pass(self, node):
        self.statement(node, 'pass')

    def visit_Print(self, node):
        # XXX: python 2.6 only
        self.statement(node, 'print ')
        values = node.values
        if node.dest is not None:
            self.write(' >> ')
            values = [node.dest] + node.values
        self.comma_list(values, not node.nl)

    def visit_Delete(self, node):
        self.statement(node, 'del ')
        self.comma_list(node.targets)

    def visit_TryExcept(self, node):
        self.statement(node, 'try:')
        self.body(node.body)
        for handler in node.handlers:
            self.visit(handler)
        self.else_body(node.orelse)

    # new for Python 3.3
    def visit_Try(self, node):
        self.statement(node, 'try:')
        self.body(node.body)
        for handler in node.handlers:
            self.visit(handler)
        if node.finalbody:
            self.statement(node, 'finally:')
            self.body(node.finalbody)
        self.else_body(node.orelse)

    def visit_ExceptHandler(self, node):
        self.statement(node, 'except')
        if node.type is not None:
            self.write(' ', node.type)
            self.conditional_write(' as ', node.name)
        self.write(':')
        self.body(node.body)

    def visit_TryFinally(self, node):
        self.statement(node, 'try:')
        self.body(node.body)
        self.statement(node, 'finally:')
        self.body(node.finalbody)

    def visit_Exec(self, node):
        dicts = node.globals, node.locals
        dicts = dicts[::-1] if dicts[0] is None else dicts
        self.statement(node, 'exec ', node.body)
        self.conditional_write(' in ', dicts[0])
        self.conditional_write(', ', dicts[1])

    def visit_Assert(self, node):
        self.statement(node, 'assert ', node.test)
        self.conditional_write(', ', node.msg)

    def visit_Global(self, node):
        self.statement(node, 'global ', ', '.join(node.names))

    def visit_Nonlocal(self, node):
        self.statement(node, 'nonlocal ', ', '.join(node.names))

    def visit_Return(self, node):
        self.statement(node, 'return')
        self.conditional_write(' ', node.value)

    def visit_Break(self, node):
        self.statement(node, 'break')

    def visit_Continue(self, node):
        self.statement(node, 'continue')

    def visit_Raise(self, node):
        # XXX: Python 2.6 / 3.0 compatibility
        self.statement(node, 'raise')
        if hasattr(node, 'exc') and node.exc is not None:
            self.write(' ', node.exc)
            self.conditional_write(' from ', node.cause)
        elif hasattr(node, 'type') and node.type is not None:
            self.write(' ', node.type)
            self.conditional_write(', ', node.inst)
            self.conditional_write(', ', node.tback)

    # Expressions

    def visit_Attribute(self, node):
        self.write(node.value, '.', node.attr)

    def visit_Call(self, node):
        want_comma = []

        def write_comma():
            if want_comma:
                self.write(', ')
            else:
                want_comma.append(True)

        self.visit(node.func)
        self.write('(')
        for arg in node.args:
            self.write(write_comma, arg)
        for keyword in node.keywords:
            self.write(write_comma, keyword.arg, '=', keyword.value)
        self.conditional_write(write_comma, '*', node.starargs)
        self.conditional_write(write_comma, '**', node.kwargs)
        self.write(')')

    def visit_Name(self, node):
        self.write(node.id)

    def visit_Str(self, node):
        self.write(repr(node.s))

    def visit_Bytes(self, node):
        self.write(repr(node.s))

    def visit_Num(self, node):
        # Hack because ** binds more closely than '-'
        s = repr(node.n)
        if s.startswith('-'):
            s = '(%s)' % s
        self.write(s)

    @enclose('()')
    def visit_Tuple(self, node):
        self.comma_list(node.elts, len(node.elts) == 1)

    @enclose('[]')
    def visit_List(self, node):
        self.comma_list(node.elts)

    @enclose('{}')
    def visit_Set(self, node):
        self.comma_list(node.elts)

    @enclose('{}')
    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            self.write(key, ': ', value, ', ')

    @enclose('()')
    def visit_BinOp(self, node):
        self.write(node.left, get_binop(node.op, ' %s '), node.right)

    @enclose('()')
    def visit_BoolOp(self, node):
        op = get_boolop(node.op, ' %s ')
        for idx, value in enumerate(node.values):
            self.write(idx and op or '', value)

    @enclose('()')
    def visit_Compare(self, node):
        self.visit(node.left)
        for op, right in zip(node.ops, node.comparators):
            self.write(get_cmpop(op, ' %s '), right)

    @enclose('()')
    def visit_UnaryOp(self, node):
        self.write(get_unaryop(node.op), ' ', node.operand)

    def visit_Subscript(self, node):
        self.write(node.value, '[', node.slice, ']')

    def visit_Slice(self, node):
        self.conditional_write(node.lower)
        self.write(':')
        self.conditional_write(node.upper)
        if node.step is not None:
            self.write(':')
            if not (isinstance(node.step, ast.Name) and
                    node.step.id == 'None'):
                self.visit(node.step)

    def visit_Index(self, node):
        self.visit(node.value)

    def visit_ExtSlice(self, node):
        self.comma_list(node.dims, len(node.dims) == 1)

    def visit_Yield(self, node):
        self.write('yield')
        self.conditional_write(' ', node.value)

    # new for Python 3.3
    def visit_YieldFrom(self, node):
        self.write('yield from ')
        self.visit(node.value)

    @enclose('()')
    def visit_Lambda(self, node):
        self.write('lambda ')
        self.signature(node.args)
        self.write(': ', node.body)

    def visit_Ellipsis(self, node):
        self.write('...')

    def generator_visit(left, right):
        def visit(self, node):
            self.write(left, node.elt)
            for comprehension in node.generators:
                self.visit(comprehension)
            self.write(right)
        return visit

    visit_ListComp = generator_visit('[', ']')
    visit_GeneratorExp = generator_visit('(', ')')
    visit_SetComp = generator_visit('{', '}')
    del generator_visit

    @enclose('{}')
    def visit_DictComp(self, node):
        self.write(node.key, ': ', node.value)
        for comprehension in node.generators:
            self.visit(comprehension)

    @enclose('()')
    def visit_IfExp(self, node):
        self.write(node.body, ' if ', node.test, ' else ', node.orelse)

    def visit_Starred(self, node):
        self.write('*', node.value)

    @enclose('``')
    def visit_Repr(self, node):
        # XXX: python 2.6 only
        self.visit(node.value)

    def visit_Module(self, node):
        for stmt in node.body:
            self.visit(stmt)

    # Helper Nodes

    def visit_arg(self, node):
        self.write(node.arg)
        self.conditional_write(': ', node.annotation)

    def visit_alias(self, node):
        self.write(node.name)
        self.conditional_write(' as ', node.asname)

    def visit_comprehension(self, node):
        self.write(' for ', node.target, ' in ', node.iter)
        if node.ifs:
            for if_ in node.ifs:
                self.write(' if ', if_)
