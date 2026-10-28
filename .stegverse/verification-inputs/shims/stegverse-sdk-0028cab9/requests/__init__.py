"""A minimal stand-in for `requests`, built on urllib, scoped to ONE verification input (E0, stdlib only).

StegVerse-org/.github#163 (P1). StegVerse-SDK pin 0028cab9 imports `requests` from `stegverse/__init__` (through
`stegverse.comparison_orchestrator` and `stegverse.comparison_transport`) without declaring it as a dependency of the
code tests/test_sdk_manifest_crossing_fidelity.py exercises. It is NOT installed and NOT a dependency of either
repository: this file is sha256-pinned in .stegverse/verification-inputs/stegverse-sdk.json (pin 0028cab9, `shims`),
declared by the one test set that needs it (input `stegverse-sdk@0028cab9`, `shims: ["requests"]`), and put on the
path only of that set's run group, after the pinned SDK tree.

It covers only what those two modules reference: `post(url, json=, headers=, timeout=)` returning an object with
`status_code`, `text`, `content`, `headers`, `ok`, `json()` and `raise_for_status()`, and the exception
`RequestException` (with `HTTPError`, `ConnectionError` and `Timeout` under it). The crossing-fidelity tests call
none of them (traced: the import is the only use); anything else is an AttributeError that names this scope.
"""
from __future__ import annotations

import json as _json
import socket as _socket
import urllib.error as _error
import urllib.request as _request

__stegverse_shim__ = "stegverse-sdk@0028cab9 requests stand-in (StegVerse-org/.github#163)"
__all__ = ["ConnectionError", "HTTPError", "RequestException", "Response", "Timeout", "post"]


class RequestException(IOError):
    """Base of every transport failure this stand-in raises (as requests.RequestException)."""


class HTTPError(RequestException):
    def __init__(self, message: str, response: "Response | None" = None):
        super().__init__(message)
        self.response = response


class ConnectionError(RequestException):  # noqa: A001 - the name the SDK catches through RequestException
    pass


class Timeout(RequestException):
    pass


class Response:
    def __init__(self, url: str, status_code: int, headers: dict, content: bytes):
        self.url, self.status_code, self.headers, self.content = url, status_code, headers, content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        return _json.loads(self.content.decode("utf-8"))  # ValueError on invalid JSON, as requests

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} error for url: {self.url}", response=self)


def post(url: str, json=None, headers=None, timeout=None, data=None) -> Response:  # noqa: A002
    body = data
    hdrs = dict(headers or {})
    if json is not None:
        body = _json.dumps(json).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    req = _request.Request(url, data=body if body is not None else b"", headers=hdrs, method="POST")
    try:
        with _request.urlopen(req, timeout=timeout) as resp:
            return Response(url, resp.status, dict(resp.headers.items()), resp.read())
    except _error.HTTPError as exc:  # a status >= 400 is a response; raise_for_status() decides
        return Response(url, exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read())
    except (_socket.timeout, TimeoutError) as exc:
        raise Timeout(str(exc)) from exc
    except (_error.URLError, OSError) as exc:
        raise ConnectionError(str(exc)) from exc


def __getattr__(name: str):
    raise AttributeError(f"requests.{name} is outside the scope of the stegverse-sdk@0028cab9 urllib stand-in "
                         "(it covers post, Response and RequestException only; StegVerse-org/.github#163)")
