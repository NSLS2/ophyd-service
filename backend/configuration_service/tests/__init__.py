"""Configuration-service tests + test-only support modules.

Marking ``tests/`` as an explicit package (rather than relying on PEP 420
namespace-package discovery) so the resolver can ``importlib.import_module``
``tests.test_classes`` reliably regardless of where pytest is invoked
from. The classes in ``tests/test_classes.py`` are registered as fake
ophyd device classes by the enrichment tests; they need to be importable
the same way ``ios_devs.Vortex`` would be in production.
"""
