from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/security-manifest.json"
CANARY_FILE = ROOT / "data/papers/privacy-canary.txt"
RELATIVE_PATH = "privacy-canary.txt"
DOCUMENT_ID = "privacy-canary-document"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--canary", default="")
    args = parser.parse_args()

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = [row for row in payload.get("documents", []) if row.get("document_id") != DOCUMENT_ID]

    if args.cleanup:
        payload["documents"] = docs
        MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        CANARY_FILE.unlink(missing_ok=True)
        print("privacy canary removed")
        return

    canary = args.canary or f"DOC_CANARY_{secrets.token_hex(16).upper()}"
    CANARY_FILE.write_text(
        "Synthetic confidential privacy-boundary document.\n"
        f"Unique marker: {canary}\n"
        "This is test data only and must never be replaced by a real credential or PII.\n",
        encoding="utf-8",
    )
    docs.append(
        {
            "corpus": "research-papers",
            "relative_path": RELATIVE_PATH,
            "document_id": DOCUMENT_ID,
            "tenant_id": "tenant-a",
            "classification": "CONFIDENTIAL",
            "is_public": False,
            "allowed_roles": ["support", "security-admin"],
            "allowed_departments": [],
            "allowed_purposes": ["research", "security-audit"],
            "shared_with_tenants": [],
            "source_version": 1,
            "policy_version": "enterprise-policy-v1",
        }
    )
    payload["documents"] = docs
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(canary)


if __name__ == "__main__":
    main()
