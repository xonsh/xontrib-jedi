"""Use Jedi as xonsh's python completer."""

# mypy: disable-error-code="attr-defined,name-defined"

import os
import re
from pathlib import Path

from xonsh.built_ins import XSH
from xonsh.completers import completer
from xonsh.completers.tools import (
    RichCompletion,
    contextual_completer,
    get_filter_function,
)
from xonsh.parsers.completion_context import CompletionContext
from xonsh.procs.pipelines import CommandPipeline, HiddenCommandPipeline

__all__ = ()

import jedi

XONSH_SPECIAL_TOKENS = {
    "?",
    "??",
    "$(",
    "${",
    "$[",
    "![",
    "!(",
    "@(",
    "@$(",
    "@",
}


XONSH_SPECIAL_TOKENS_FIRST = {tok[0] for tok in XONSH_SPECIAL_TOKENS}

# Names bound in Jedi's Interpreter namespace as typed placeholders. Each name
# is chosen to make the intended Python type obvious at the substitution site.
DUMMY_STR = "__dummy_str__"
DUMMY_LIST_STR = "__dummy_list_str__"
DUMMY_PATH = "__dummy_Path__"
DUMMY_LIST_PATH = "__dummy_list_Path__"
DUMMY_DICT = "__dummy_dict__"
DUMMY_LIST_DICT = "__dummy_list_dict__"
DUMMY_COMMAND_PIPELINE = "__dummy_CommandPipeline__"
DUMMY_HIDDEN_COMMAND_PIPELINE = "__dummy_HiddenCommandPipeline__"


def _make_jedi_placeholder(cls):
    """Build an uninitialized instance of ``cls`` for Jedi to introspect."""
    return cls.__new__(cls)


_JEDI_PLACEHOLDER_VALUES = {
    DUMMY_STR: "",
    DUMMY_LIST_STR: [""],
    DUMMY_PATH: Path(),
    DUMMY_LIST_PATH: [Path()],
    DUMMY_DICT: {},
    DUMMY_LIST_DICT: [{}],
    DUMMY_COMMAND_PIPELINE: _make_jedi_placeholder(CommandPipeline),
    DUMMY_HIDDEN_COMMAND_PIPELINE: _make_jedi_placeholder(HiddenCommandPipeline),
}

# Xonsh ``$(...)`` command decorators that change the captured return type,
# mapped to the placeholder name representing the resulting Python type.
# Decorators not listed here (``@noerr``, ``@thread``, ...) do not affect the
# return type and are simply skipped.
_CAPTURED_STDOUT_DECORATOR_TYPES = {
    "lines": DUMMY_LIST_STR,
    "path": DUMMY_PATH,
    "paths": DUMMY_LIST_PATH,
    "json": DUMMY_DICT,
    "jsonl": DUMMY_LIST_DICT,
    "yaml": DUMMY_DICT,
}

_DECORATOR_RE = re.compile(r"@(\w+)")


def _detect_captured_stdout_placeholder(source, inner_start, inner_end):
    """Pick the placeholder name for the captured stdout of a ``$(...)`` form.

    Scans leading ``@decorator`` tokens inside ``$(...)`` and returns the
    placeholder for the last decorator whose output type we recognize.
    Defaults to :data:`DUMMY_STR` (plain ``str`` capture).
    """
    placeholder = DUMMY_STR
    i = inner_start
    while i < inner_end:
        while i < inner_end and source[i] in " \t":
            i += 1
        if i >= inner_end or source[i] != "@":
            break
        m = _DECORATOR_RE.match(source, i)
        if m is None or m.end() > inner_end:
            break
        name = m.group(1)
        if name in _CAPTURED_STDOUT_DECORATOR_TYPES:
            placeholder = _CAPTURED_STDOUT_DECORATOR_TYPES[name]
        i = m.end()
    return placeholder


# (opening token, closing char, fixed placeholder name or None).
# A ``None`` placeholder means it is resolved dynamically from ``$(@...)``
# decorators. ``![`` must come before ``!(`` so the longer prefix wins.
_JEDI_SUBEXPR_FORMS = (
    ("$(", ")", None),
    ("![", "]", DUMMY_HIDDEN_COMMAND_PIPELINE),
    ("!(", ")", DUMMY_COMMAND_PIPELINE),
)


def _find_subexpr_close(source, start, open_tok, close_char):
    """Find the index of ``close_char`` that closes the subexpression at ``start``.

    Tracks balancing of the same delimiter pair as ``open_tok`` and skips quoted
    strings. Returns ``None`` if the subexpression is unclosed.
    """
    open_char = open_tok[-1]
    quote = None
    depth = 1
    index = start + len(open_tok)

    while index < len(source):
        if quote is not None:
            if quote in ("'", '"') and source[index] == "\\":
                index += 2
                continue
            if source.startswith(quote, index):
                index += len(quote)
                quote = None
                continue
            index += 1
            continue

        if source.startswith("'''", index) or source.startswith('"""', index):
            quote = source[index : index + 3]
            index += 3
            continue

        char = source[index]
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1

    return None


def _rewrite_xonsh_subexprs(source, cursor_index):
    """Rewrite ``$()``/``!()``/``![]`` subexpressions to typed Jedi placeholders.

    Returns ``(transformed_source, transformed_cursor_index)``.
    """
    rewritten = []
    transformed_index = 0
    index = 0
    n = len(source)

    while index < n:
        match = None
        for open_tok, close_char, fixed_placeholder in _JEDI_SUBEXPR_FORMS:
            if source.startswith(open_tok, index):
                closing = _find_subexpr_close(source, index, open_tok, close_char)
                if closing is not None:
                    if fixed_placeholder is None:
                        placeholder = _detect_captured_stdout_placeholder(
                            source, index + len(open_tok), closing
                        )
                    else:
                        placeholder = fixed_placeholder
                    match = (placeholder, closing)
                break
        if match is not None:
            placeholder, closing = match
            rewritten.append(placeholder)
            if cursor_index > index:
                transformed_index += len(placeholder)
            index = closing + 1
            continue

        rewritten.append(source[index])
        if index < cursor_index:
            transformed_index += 1
        index += 1

    return "".join(rewritten), transformed_index


@contextual_completer
def complete_jedi(context: CompletionContext):
    """Completes python code using Jedi and xonsh operators"""
    if context.python is None:
        return None

    ctx = context.python.ctx or {}

    # if the first word is a known command (and we're not completing it), don't complete.
    # taken from xonsh/completers/python.py
    if context.command and context.command.arg_index != 0:
        first = context.command.args[0].value
        if first in XSH.commands_cache and first not in ctx:  # type: ignore
            return None

    # if we're completing a possible command and the prefix contains a valid path, don't complete.
    if context.command:
        path_dir = os.path.dirname(context.command.prefix)
        if path_dir and os.path.isdir(os.path.expanduser(path_dir)):
            return None

    filter_func = get_filter_function()
    jedi.settings.case_insensitive_completion = not XSH.env.get(
        "CASE_SENSITIVE_COMPLETIONS"
    )

    source = context.python.multiline_code
    index = context.python.cursor_index
    source, index = _rewrite_xonsh_subexprs(source, index)
    row = source.count("\n", 0, index) + 1
    column = (
        index - source.rfind("\n", 0, index) - 1
    )  # will be `index - (-1) - 1` if there's no newline

    extra_ctx = {"__xonsh__": XSH, **_JEDI_PLACEHOLDER_VALUES}
    try:
        extra_ctx["_"] = _
    except NameError:
        pass

    script = jedi.Interpreter(source, [ctx, extra_ctx])

    script_comp = set()
    try:
        script_comp = script.complete(row, column)
    except Exception:
        pass

    res = {create_completion(comp) for comp in script_comp if should_complete(comp)}

    if index > 0:
        last_char = source[index - 1]
        res.update(
            RichCompletion(t, prefix_len=1)
            for t in XONSH_SPECIAL_TOKENS
            if filter_func(t, last_char)
        )
    else:
        res.update(RichCompletion(t, prefix_len=0) for t in XONSH_SPECIAL_TOKENS)

    return res


def should_complete(comp: jedi.api.classes.Completion):
    """Make sure _* names are completed only when
    the user writes the first underscore
    """
    name = comp.name
    if not name.startswith("_"):
        return True
    completion = comp.complete
    # only if we're not completing the first underscore:
    return completion and len(completion) <= len(name) - 1


def create_completion(comp: jedi.api.classes.Completion):
    """Create a RichCompletion from a Jedi Completion object"""
    comp_type = None
    description = None

    if comp.type != "instance":
        sigs = comp.get_signatures()
        if sigs:
            comp_type = comp.type
            description = sigs[0].to_string()
    if comp_type is None:
        # jedi doesn't know exactly what this is
        inf = comp.infer()
        if inf:
            comp_type = inf[0].type
            description = inf[0].description

    display = comp.name + ("()" if comp_type == "function" else "")
    description = description or comp.type

    prefix_len = len(comp.name) - len(comp.complete)

    return RichCompletion(
        comp.name,
        display=display,
        description=description,
        prefix_len=prefix_len,
    )


# Jedi ignores leading '@(' and friends
completer.add_one_completer("jedi_python", complete_jedi, "<python")
completer.remove_completer("python")
