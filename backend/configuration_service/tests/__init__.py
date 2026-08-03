"""Configuration-service tests + test-only support modules.

Marking ``tests/`` as an explicit package (rather than relying on PEP 420
namespace-package discovery) so the resolver can ``importlib.import_module``
test-local device classes (``tests.<module>.<Class>`` device_class paths)
reliably regardless of where pytest is invoked from — the same way
``ios_devs.Vortex`` would be importable in production.
"""
