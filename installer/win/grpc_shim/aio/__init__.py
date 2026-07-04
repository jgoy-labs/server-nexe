"""Part of the Windows ARM64 grpc stub — see the package __init__."""

from grpc import _make_dummy


def __getattr__(name):
    return _make_dummy(name)
