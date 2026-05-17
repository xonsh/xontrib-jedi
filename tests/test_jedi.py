"""Tests for the Jedi completer xontrib"""

import importlib
import sys
from unittest.mock import MagicMock, call

import pytest
from xonsh.completers.tools import RichCompletion
from xonsh.parsers.completion_context import CompletionContext, PythonContext
from xonsh.pytest.tools import skip_if_on_windows
from xonsh.xontribs import find_xontrib


@pytest.fixture
def jedi_mock(monkeypatch):
    jedi_mock = MagicMock()
    jedi_mock.__version__ = "0.16.0"
    jedi_mock.Interpreter().complete.return_value = []
    jedi_mock.reset_mock()
    monkeypatch.setitem(sys.modules, "jedi", jedi_mock)
    yield jedi_mock


@pytest.fixture
def completer_mock(monkeypatch, xession):
    completer_mock = MagicMock()

    # so that args will be passed
    def comp(args):
        completer_mock(args)

    monkeypatch.setitem(xession.aliases, "completer", comp)
    yield completer_mock


@pytest.fixture
def jedi_xontrib(monkeypatch, source_path, jedi_mock, completer_mock, xession):
    monkeypatch.syspath_prepend(source_path)
    spec = find_xontrib("jedi")
    module = importlib.import_module(spec.name)
    module._load_xontrib_(xsh=xession)
    yield module
    module._unload_xontrib_(xsh=xession)
    del sys.modules[spec.name]


def test_completer_added(jedi_xontrib, xession):
    assert "xontrib.jedi" in sys.modules
    assert "python" not in xession.completers
    assert "python_mode" not in xession.completers
    assert "jedi_python" in xession.completers


def test_unload_restores_python_completer(
    monkeypatch, source_path, jedi_mock, completer_mock, xession
):
    monkeypatch.syspath_prepend(source_path)
    spec = find_xontrib("jedi")
    module = importlib.import_module(spec.name)
    try:
        module._load_xontrib_(xsh=xession)
        assert "jedi_python" in xession.completers
        assert "python" not in xession.completers

        module._unload_xontrib_(xsh=xession)
        assert "jedi_python" not in xession.completers
        assert "python" in xession.completers
    finally:
        del sys.modules[spec.name]


@pytest.mark.parametrize(
    "context",
    [
        CompletionContext(python=PythonContext("10 + x", 6)),
    ],
)
def test_jedi_api(jedi_xontrib, jedi_mock, context, xession):
    jedi_xontrib.complete_jedi(context)

    extra_namespace = {"__xonsh__": xession}
    try:
        extra_namespace["_"] = _
    except NameError:
        pass
    namespaces = [{}, extra_namespace]

    line = context.python.multiline_code
    end = context.python.cursor_index

    assert jedi_mock.Interpreter.call_args_list == [call(line, namespaces)]
    assert jedi_mock.Interpreter().complete.call_args_list == [call(1, end)]


def test_multiline(jedi_xontrib, jedi_mock, monkeypatch):
    complete_document = "xx = 1\n1 + x"
    jedi_xontrib.complete_jedi(
        CompletionContext(
            python=PythonContext(complete_document, len(complete_document))
        )
    )

    assert jedi_mock.Interpreter.call_args_list[0][0][0] == complete_document
    assert jedi_mock.Interpreter().complete.call_args_list == [
        call(2, 5)  # line (one-indexed), column (zero-indexed)
    ]


@pytest.mark.parametrize(
    "completion, rich_completion",
    [
        (
            # from jedi when code is 'x' and xx=3
            (
                "instance",
                "xx",
                "x",
                "int(x=None, /) -> int",
                ("instance", "instance int"),
            ),
            RichCompletion(
                "xx", display="xx", description="instance int", prefix_len=1
            ),
        ),
        (
            # from jedi when code is 'xx=3\nx'
            ("statement", "xx", "x", None, ("instance", "instance int")),
            RichCompletion(
                "xx", display="xx", description="instance int", prefix_len=1
            ),
        ),
        (
            # from jedi when code is 'x.' and x=3
            (
                "function",
                "from_bytes",
                "from_bytes",
                "from_bytes(bytes, byteorder, *, signed=False)",
                ("function", "def __get__"),
            ),
            RichCompletion(
                "from_bytes",
                display="from_bytes()",
                description="from_bytes(bytes, byteorder, *, signed=False)",
            ),
        ),
        (
            # from jedi when code is 'x=3\nx.'
            ("function", "imag", "imag", None, ("instance", "instance int")),
            RichCompletion("imag", display="imag", description="instance int"),
        ),
        (
            # from '(3).from_bytes(byt'
            ("param", "bytes=", "es=", None, ("instance", "instance Sequence")),
            RichCompletion(
                "bytes=",
                display="bytes=",
                description="instance Sequence",
                prefix_len=3,
            ),
        ),
        (
            # from 'x.from_bytes(byt' when x=3
            ("param", "bytes=", "es=", None, None),
            RichCompletion(
                "bytes=", display="bytes=", description="param", prefix_len=3
            ),
        ),
        (
            # from 'import colle'
            ("module", "collections", "ctions", None, ("module", "module collections")),
            RichCompletion(
                "collections",
                display="collections",
                description="module collections",
                prefix_len=5,
            ),
        ),
        (
            # from 'NameErr'
            (
                "class",
                "NameError",
                "or",
                "NameError(*args: object)",
                ("class", "class NameError"),
            ),
            RichCompletion(
                "NameError",
                display="NameError",
                description="NameError(*args: object)",
                prefix_len=7,
            ),
        ),
        (
            # from 'a["' when a={'name':None}
            ("string", '"name"', 'name"', None, None),
            RichCompletion('"name"', display='"name"', description="string"),
        ),
        (
            # from 'open("/etc/pass'
            ("path", 'passwd"', 'wd"', None, None),
            RichCompletion(
                'passwd"', display='passwd"', description="path", prefix_len=4
            ),
        ),
        (
            # from 'cla'
            ("keyword", "class", "ss", None, None),
            RichCompletion(
                "class", display="class", description="keyword", prefix_len=3
            ),
        ),
    ],
)
def test_rich_completions(jedi_xontrib, jedi_mock, completion, rich_completion):
    comp_type, comp_name, comp_complete, sig, inf = completion
    comp_mock = MagicMock()
    comp_mock.type = comp_type
    comp_mock.name = comp_name
    comp_mock.complete = comp_complete
    if sig:
        sig_mock = MagicMock()
        sig_mock.to_string.return_value = sig
        comp_mock.get_signatures.return_value = [sig_mock]
    else:
        comp_mock.get_signatures.return_value = []
    if inf:
        inf_type, inf_desc = inf
        inf_mock = MagicMock()
        inf_mock.type = inf_type
        inf_mock.description = inf_desc
        comp_mock.infer.return_value = [inf_mock]
    else:
        comp_mock.infer.return_value = []

    jedi_xontrib.XONSH_SPECIAL_TOKENS = []
    jedi_mock.Interpreter().complete.return_value = [comp_mock]
    completions = jedi_xontrib.complete_jedi(
        CompletionContext(python=PythonContext("", 0))
    )
    assert len(completions) == 1
    (ret_completion,) = completions
    assert isinstance(ret_completion, RichCompletion)
    assert ret_completion == rich_completion
    assert ret_completion.display == rich_completion.display
    assert ret_completion.description == rich_completion.description


def test_bad_completion_does_not_drop_others(jedi_xontrib, jedi_mock):
    """If jedi raises on one Completion (e.g. inside ``infer()``), the
    rest of the batch must still come through — with the broken one
    falling back to a bare ``RichCompletion(comp.name)``."""
    good = MagicMock()
    good.type = "instance"
    good.name = "good_name"
    good.complete = ""
    good.get_signatures.return_value = []
    good_inf = MagicMock(type="instance", description="instance int")
    good.infer.return_value = [good_inf]

    bad = MagicMock()
    bad.type = "module"
    bad.name = "bad_name"
    bad.complete = ""
    bad.get_signatures.side_effect = RuntimeError("jedi blew up")
    bad.infer.side_effect = RuntimeError("jedi blew up")

    jedi_xontrib.XONSH_SPECIAL_TOKENS = []
    jedi_mock.Interpreter().complete.return_value = [good, bad]
    completions = jedi_xontrib.complete_jedi(
        CompletionContext(python=PythonContext("", 0))
    )
    by_name = {c.value: c for c in completions}
    assert set(by_name) == {"good_name", "bad_name"}
    assert by_name["good_name"].description == "instance int"
    # bad one falls back to bare RichCompletion — no description attached
    assert by_name["bad_name"].description == ""


def test_special_tokens(jedi_xontrib):
    assert jedi_xontrib.complete_jedi(
        CompletionContext(python=PythonContext("", 0))
    ).issuperset(jedi_xontrib.XONSH_SPECIAL_TOKENS)
    assert jedi_xontrib.complete_jedi(
        CompletionContext(python=PythonContext("@", 1))
    ) == {"@", "@(", "@$("}
    assert jedi_xontrib.complete_jedi(
        CompletionContext(python=PythonContext("$", 1))
    ) == {"$[", "${", "$("}


@skip_if_on_windows
def test_no_command_path_completion(jedi_xontrib, completion_context_parse):
    assert jedi_xontrib.complete_jedi(completion_context_parse("./", 2)) is None
    assert jedi_xontrib.complete_jedi(completion_context_parse("~/", 2)) is None
    assert jedi_xontrib.complete_jedi(completion_context_parse("./e", 3)) is None
    assert jedi_xontrib.complete_jedi(completion_context_parse("/usr/bin/", 9)) is None
    assert (
        jedi_xontrib.complete_jedi(completion_context_parse("/usr/bin/e", 10)) is None
    )
