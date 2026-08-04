from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast


class CredentialStoreError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


class CredentialStore(Protocol):
    def put(self, reference: str, secret: str, username: str | None = None) -> None: ...

    def get(self, reference: str) -> str: ...

    def delete(self, reference: str) -> None: ...


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

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class UnavailableCredentialStore:
    def put(self, reference: str, secret: str, username: str | None = None) -> None:
        del reference, secret, username
        raise CredentialStoreError("Windows Credential Manager is required for saving credentials")

    def get(self, reference: str) -> str:
        del reference
        raise CredentialStoreError("Windows Credential Manager is required for reading credentials")

    def delete(self, reference: str) -> None:
        del reference
        raise CredentialStoreError(
            "Windows Credential Manager is required for deleting credentials"
        )


class ReadOnlyFileCredentialStore:
    """Read secrets from a fixed, least-privilege directory mounted by the host."""

    _MAX_SECRET_BYTES = 65_536

    def __init__(self, directory: Path) -> None:
        if not directory.is_absolute():
            raise CredentialStoreError("credential directory must be absolute")
        self._directory = directory.resolve()

    def _path(self, reference: str) -> Path:
        filename = self.filename_for_reference(reference)
        candidate = self._directory / filename
        if candidate.is_symlink():
            raise CredentialStoreError("credential reference must not be a symlink")
        path = candidate.resolve()
        if path.parent != self._directory:
            raise CredentialStoreError("credential reference escapes the configured directory")
        return path

    @staticmethod
    def filename_for_reference(reference: str) -> str:
        if not reference or len(reference) > 255 or any(ord(value) < 32 for value in reference):
            raise CredentialStoreError("credential reference is empty or invalid")
        digest = sha256(reference.encode("utf-8")).hexdigest()
        return f"sha256-{digest}.secret"

    def put(self, reference: str, secret: str, username: str | None = None) -> None:
        del reference, secret, username
        raise CredentialStoreError("cloud-mounted credentials are read-only")

    def get(self, reference: str) -> str:
        path = self._path(reference)
        try:
            metadata = path.stat()
        except OSError as error:
            raise CredentialStoreError("credential reference was not found") from error
        if not path.is_file():
            raise CredentialStoreError("credential reference must be a regular non-symlink file")
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise CredentialStoreError("credential file must not grant group or world permissions")
        if metadata.st_size > self._MAX_SECRET_BYTES:
            raise CredentialStoreError("credential file exceeds the maximum supported size")
        try:
            raw = path.read_bytes()
            value = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CredentialStoreError("credential reference could not be read as UTF-8") from error
        return value.removesuffix("\n").removesuffix("\r")

    def delete(self, reference: str) -> None:
        del reference
        raise CredentialStoreError("cloud-mounted credentials are read-only")


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

        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            raise CredentialStoreError("Windows Credential Manager is unavailable")
        advapi32 = win_dll("Advapi32.dll", use_last_error=True)
        advapi32.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(Credential)),
        ]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        advapi32.CredDeleteW.restype = wintypes.BOOL
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
            return cast(str, raw.decode("utf-16-le"))
        finally:
            advapi32.CredFree(pointer)

    def delete(self, reference: str) -> None:
        ctypes, advapi32, _credential_type = self._bindings()
        if advapi32.CredDeleteW(reference, self._CRED_TYPE_GENERIC, 0):
            return
        error_code = ctypes.get_last_error()
        if error_code != 1168:
            raise CredentialStoreError(f"credential reference could not be deleted ({error_code})")


def create_credential_store() -> CredentialStore:
    backend = os.getenv("CLOUD_STUDY_CREDENTIAL_STORE", "auto").strip()
    if backend == "file":
        configured_directory = os.getenv("CLOUD_STUDY_SECRET_DIRECTORY", "").strip()
        if not configured_directory:
            raise CredentialStoreError(
                "CLOUD_STUDY_SECRET_DIRECTORY is required for the file credential store"
            )
        return ReadOnlyFileCredentialStore(Path(configured_directory))
    if backend not in {"auto", "windows"}:
        raise CredentialStoreError("CLOUD_STUDY_CREDENTIAL_STORE must be auto, windows, or file")
    if os.name == "nt":
        return WindowsCredentialStore()
    return UnavailableCredentialStore()
