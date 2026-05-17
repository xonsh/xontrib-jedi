"""Use Jedi as xonsh's python completer."""

# mypy: disable-error-code="attr-defined,name-defined"

import os
import traceback

from xonsh.built_ins import XSH
from xonsh.completers import completer
from xonsh.completers.tools import (
    RichCompletion,
    contextual_completer,
)
from xonsh.parsers.completion_context import CompletionContext
from xonsh.tools import print_above_prompt


def _log_jedi_exc(where: str) -> None:
    """Surface a swallowed jedi exception when the user opted in.

    Gated on ``$XONSH_DEBUG`` (general xonsh debugging) or
    ``$XONSH_COMPLETER_TRACE`` (completer-pipeline debugging). Uses
    ``print_above_prompt`` so the trace doesn't overwrite the active
    prompt-toolkit input line.
    """
    env = XSH.env or {}
    if env.get("XONSH_DEBUG") or env.get("XONSH_COMPLETER_TRACE"):
        print_above_prompt(
            f"xontrib-jedi: jedi raised in {where}\n{traceback.format_exc()}"
        )

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

    jedi.settings.case_insensitive_completion = not XSH.env.get(
        "CASE_SENSITIVE_COMPLETIONS"
    )

    source = context.python.multiline_code
    index = min(context.python.cursor_index, len(source))
    row = source.count("\n", 0, index) + 1
    column = (
        index - source.rfind("\n", 0, index) - 1
    )  # will be `index - (-1) - 1` if there's no newline

    extra_ctx = {"__xonsh__": XSH}
    try:
        extra_ctx["_"] = _
    except NameError:
        pass

    script = jedi.Interpreter(source, [ctx, extra_ctx])

    fuzzy = bool(XSH.env.get("XONTRIB_JEDI_FUZZY"))

    script_comp = set()
    try:
        script_comp = script.complete(row, column, fuzzy=fuzzy)
    except Exception:
        _log_jedi_exc("script.complete")

    res = {create_completion(comp) for comp in script_comp if should_complete(comp)}

    if index > 0:
        last_char = source[index - 1]
        # Spec-tokens are operators; only prefix matches make sense here.
        # $XONSH_COMPLETER_MODE="substring_tier" would otherwise offer e.g.
        # `@$(` when the user types `$`.
        res.update(
            RichCompletion(t, prefix_len=1)
            for t in XONSH_SPECIAL_TOKENS
            if t.startswith(last_char)
        )
    else:
        res.update(RichCompletion(t, prefix_len=0) for t in XONSH_SPECIAL_TOKENS)

    return res


def should_complete(comp: jedi.api.classes.Completion):
    """Hide underscore-prefixed names until the user has typed at least
    the leading underscore.

    ``comp.complete`` is the tail jedi wants to insert; when its length
    is less than the name's, the user has already typed the difference.
    A fully-typed name (``comp.complete == ""``) is still worth showing
    so that the description / signature ends up in the popup.
    """
    name = comp.name
    return not name.startswith("_") or len(comp.complete) <= len(name) - 1


def create_completion(comp: jedi.api.classes.Completion):
    """Create a RichCompletion from a Jedi Completion object.

    ``get_signatures()`` and ``infer()`` can raise on some types; we fall
    back to a bare ``RichCompletion(comp.name)`` so one bad completion
    doesn't drop the rest of the set.
    """
    try:
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
    except Exception:
        _log_jedi_exc("create_completion")
        return RichCompletion(comp.name)


def _load_xontrib_(xsh, **_):
    """Replace the default ``python`` completer with the jedi-backed one."""
    xsh.env.register(
        "XONTRIB_JEDI_FUZZY",
        type="bool",
        default=False,
        doc=(
            "When True, ``xontrib-jedi`` calls ``jedi.complete(..., fuzzy=True)``, "
            "so e.g. ``ooa`` matches ``foobar``. Off by default — fuzzy mode "
            "returns more noisy candidates."
        ),
    )
    # Jedi ignores leading '@(' and friends, so insert before `python` and
    # then drop the original.
    completer.add_one_completer("jedi_python", complete_jedi, "<python")
    completer.remove_completer("python")
    return {}


def _unload_xontrib_(xsh, **_):
    """Restore the default xonsh ``python`` completer."""
    from xonsh.completers.python import complete_python

    completer.remove_completer("jedi_python")
    # `<path` reproduces the original slot for `python` (last in defaults).
    completer.add_one_completer("python", complete_python, "<path")
    xsh.env.deregister("XONTRIB_JEDI_FUZZY")
