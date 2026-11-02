"""Render a new realm import without contacting or modifying an identity provider."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from ontology_platform.security.broker import realm_configuration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--studio-origin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entra-tenant", type=UUID)
    parser.add_argument("--entra-client")
    parser.add_argument("--google-client")
    parser.add_argument("--workspace-client")
    parser.add_argument("--workspace-domain")
    args = parser.parse_args()
    result = realm_configuration(
        args.issuer,
        args.studio_origin,
        entra_tenant=args.entra_tenant,
        entra_client=args.entra_client,
        google_client=args.google_client,
        workspace_client=args.workspace_client,
        workspace_domain=args.workspace_domain,
    )
    # Never overwrite a realm export/credential backup.
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print("Rendered new realm import; no provider configuration has been applied")


if __name__ == "__main__":
    main()
