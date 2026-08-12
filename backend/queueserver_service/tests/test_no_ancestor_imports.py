"""Guard: runtime code imports nothing from the ancestor/client distributions.

queueserver_service is the in-tree merger of bluesky-queueserver and
bluesky-httpserver; its manager client is an in-tree port of
bluesky-queueserver-api's async 0MQ path. The ancestors' import names exist in
this repo only as OUTBOUND compatibility surfaces (the shim packages, which
import FROM queueserver_service for external consumers). Runtime code must
never import them: the dependency direction is one-way by decision, and this
test is what keeps a convenient `import bluesky_queueserver_api` from creeping
back in a refactor.

Tests are exempt — the Side-C compatibility suite deliberately drives the real
published client against the service.
"""

import ast
import pathlib

FORBIDDEN = ("bluesky_queueserver", "bluesky_queueserver_api", "bluesky_httpserver")

RUNTIME_ROOT = pathlib.Path(__file__).parent.parent / "queueserver_service"


def _imported_roots(path: pathlib.Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0], node.lineno


def test_runtime_code_has_no_ancestor_imports():
    offenders = []
    for py in sorted(RUNTIME_ROOT.rglob("*.py")):
        for root, lineno in _imported_roots(py):
            if root in FORBIDDEN:
                offenders.append(f"{py.relative_to(RUNTIME_ROOT.parent)}:{lineno}: imports {root}")
    assert not offenders, (
        "runtime code must not import ancestor/client distributions "
        "(they are outbound compat shims only):\n" + "\n".join(offenders)
    )
