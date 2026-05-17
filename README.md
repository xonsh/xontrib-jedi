<p align="center">
Xonsh Python completions using <a href="https://jedi.readthedocs.io/en/latest/">jedi</a>.
</p>

<p align="center">
If you like the idea click ⭐ on the repo and <a href="https://twitter.com/intent/tweet?text=Nice%20xontrib%20for%20the%20xonsh%20shell!&url=https://github.com/xonsh/xontrib-jedi" target="_blank">tweet</a>.
</p>


## Installation

To install use pip:

```bash
xpip install xontrib-jedi
# or: xpip install -U git+https://github.com/xonsh/xontrib-jedi
```

## Usage

```xsh
xontrib load jedi

import json
json.<Tab>
```

The xontrib swaps xonsh's built-in `python` completer for `jedi_python`.
Other completers in the chain (including `xonsh_imp`, which completes
`__xonsh__.imp.<module>`) are left alone, so they keep working as before.

Operator and shell-syntax tokens (`<=`, `**`, `$(`, `@(`, `,`, …) are pulled
from xonsh's own `XONSH_EXPR_TOKENS`, so the menu stays in sync with the
host xonsh version. Keywords already produced by jedi (`if`, `and`, `lambda`,
…) are filtered out to avoid duplicates.

## Configuration

- `$XONTRIB_JEDI_FUZZY` (`bool`, default `False`) — when `True`, jedi is called
  with `fuzzy=True`, so e.g. `ooa` matches `foobar`. Off by default since fuzzy
  mode returns more noisy candidates.

Enable fuzzy matching for the current session:

```xsh
$XONTRIB_JEDI_FUZZY = True
```

## Release

- update the version in `pyproject.toml`
- Create a new release with the same tag using Github releases

## Credits

This package was created with [xontrib template](https://github.com/xonsh/xontrib-template).
