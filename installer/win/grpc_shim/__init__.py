"""grpc stub for Windows ARM64 — vendored into the sidecar bundle.

grpcio has NO win_arm64 wheel (any version), yet qdrant-client imports `grpc`
unconditionally (interceptors in connection.py / core/qdrant_pool.py) even when
the product runs in embedded/local mode and never opens a gRPC channel. This
package satisfies those imports and class definitions. If any code path actually
USED gRPC it would fail — and it should, because on ARM64 there is no transport.

Scope: shipped ONLY in the Windows ARM64 build (grpcio has no wheel there). The
Windows x86_64 build uses the official grpcio wheel and does NOT vendor this shim.
build-sidecar.sh copies this directory to site-packages/grpc after installing
qdrant-client with --no-deps.

Design: every resolved attribute is a dummy CLASS (qdrant-client subclasses them,
e.g. `class _GenericClientInterceptor(grpc.UnaryUnaryClientInterceptor, ...)`),
via a metaclass that resolves class attributes plus a per-instance __getattr__.
"""

__version__ = "1.99.0"


class _DummyMeta(type):
    def __getattr__(cls, name):
        return _make_dummy(name)


def _make_dummy(name):
    return _DummyMeta(
        f"GrpcStub_{name}",
        (object,),
        {
            "__init__": lambda self, *a, **k: None,
            "__call__": lambda self, *a, **k: self,
            "__getattr__": lambda self, n: _make_dummy(n),
        },
    )


def __getattr__(name):
    return _make_dummy(name)
