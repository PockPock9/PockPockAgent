"""Protects MCP server secrets (environment values, Authorization headers) at rest.

On Windows the value is encrypted with DPAPI for the current user (``CryptProtectData``), the same
protection Electron's safeStorage uses for cloud keys, so the file is useless to another user or on
another PC. On macOS and Linux there is no dependency-free equivalent yet: the value is stored
base64-encoded in a file only the user can read (mode 600), which is what OpenClaw's own
configuration offered before. ``protected()`` says which one applies.
"""

from __future__ import annotations

import base64
import sys

PREFIX_DPAPI = "dpapi:"
PREFIX_PLAIN = "plain:"


def protected() -> bool:
    """True when secrets are encrypted at rest on this platform."""
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _UI_FORBIDDEN = 0x1

    def _call(function, data: bytes) -> bytes:
        buffer = ctypes.create_string_buffer(data, len(data))
        source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        target = _Blob()
        if not function(ctypes.byref(source), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(target)):
            raise ValueError("The secret could not be protected or read on this PC.")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            _kernel32.LocalFree(target.pbData)

    def _encrypt(data: bytes) -> bytes:
        return _call(_crypt32.CryptProtectData, data)

    def _decrypt(data: bytes) -> bytes:
        return _call(_crypt32.CryptUnprotectData, data)


def seal(text: str) -> str:
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        return PREFIX_DPAPI + base64.b64encode(_encrypt(raw)).decode("ascii")
    return PREFIX_PLAIN + base64.b64encode(raw).decode("ascii")


def unseal(value: str) -> str:
    """The secret, or raises ``ValueError`` when it cannot be read (for example, copied from another PC)."""
    if value.startswith(PREFIX_DPAPI):
        if sys.platform != "win32":
            raise ValueError("This secret was saved on Windows and cannot be read here.")
        return _decrypt(base64.b64decode(value[len(PREFIX_DPAPI):])).decode("utf-8")
    if value.startswith(PREFIX_PLAIN):
        return base64.b64decode(value[len(PREFIX_PLAIN):]).decode("utf-8")
    raise ValueError("The saved secret is not in a known format.")
