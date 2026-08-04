from __future__ import annotations

import argparse
import json

from cloud_study_api.credentials import (
    CredentialStoreError,
    ReadOnlyFileCredentialStore,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive the cloud read-only secret filename for a database reference.",
    )
    parser.add_argument("--reference", required=True)
    arguments = parser.parse_args()
    try:
        filename = ReadOnlyFileCredentialStore.filename_for_reference(
            arguments.reference
        )
    except CredentialStoreError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "filename": filename}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
