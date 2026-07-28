from __future__ import annotations

import os
from typing import Any, Protocol


class CredentialStoreError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


class CredentialStore(Protocol):
    def put(self, reference: str, secret: str, username: str | None = None) -> None: ...

    def get(self, reference: str) -> str: ...


class MemoryCredentialStore:
    """Test-only in-memory implementation."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put(self, reference: str, secret: str, username: str | None = None) -> None:
        del username
        self._values[reference] = secret

    def get(self, reference: str) -> str:
        try:
            return self._values[reference]
        except KeyError as error:
            raise CredentialStoreError("credential reference was not found") from error


class UnavailableCredentialStore:
    def put(self, reference: str, secret: str, username: str | None = None) -> None:
        del reference, secret, username
        raise CredentialStoreError("Windows Credential Manager is required for saving credentials")

    def get(self, reference: str) -> str:
        del reference
        raise CredentialStoreError("Windows Credential Manager is required for reading credentials")


class WindowsCredentialStore:
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2

    @staticmethod
    def _bindings() -> tuple[Any, Any, Any]:
        import ctypes
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        advapi32.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(Credential)),
        ]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        return ctypes, advapi32, Credential

    def put(self, reference: str, secret: str, username: str | None = None) -> None:
        ctypes, advapi32, credential_type = self._bindings()
        encoded = secret.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = credential_type()
        credential.Type = self._CRED_TYPE_GENERIC
        credential.TargetName = reference
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(
            blob,
            ctypes.POINTER(ctypes.c_ubyte),
        )
        credential.Persist = self._CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username or ""
        if not advapi32.CredWriteW(ctypes.byref(credential), 0):
            error_code = ctypes.get_last_error()
            raise CredentialStoreError(
                f"Windows Credential Manager rejected the credential ({error_code})"
            )

    def get(self, reference: str) -> str:
        ctypes, advapi32, credential_type = self._bindings()
        pointer = ctypes.POINTER(credential_type)()
        if not advapi32.CredReadW(
            reference,
            self._CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            error_code = ctypes.get_last_error()
            raise CredentialStoreError(f"credential reference could not be read ({error_code})")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return raw.decode("utf-16-le")
        finally:
            advapi32.CredFree(pointer)


def create_credential_store() -> CredentialStore:
    if os.name == "nt":
        return WindowsCredentialStore()
    return UnavailableCredentialStore()
