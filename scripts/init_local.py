"""Create local configuration once; preserve any existing developer configuration."""

import os
import secrets
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    if destination.exists():
        print("Existing .env preserved; configure it using .env.example if needed.")
        return
    password = secrets.token_urlsafe(32)
    contents = (
        (root / ".env.example")
        .read_text(encoding="utf-8")
        .replace("replace-with-a-random-local-password", password)
    )
    local_cli = root / "runtime/tools/pulumi" / ("pulumi.exe" if os.name == "nt" else "pulumi")
    if local_cli.exists():
        contents = contents.replace("OLIXOPS_PULUMI_CLI=pulumi", f"OLIXOPS_PULUMI_CLI={local_cli}")
    with destination.open("x", encoding="utf-8") as stream:
        os.chmod(destination, 0o600)
        stream.write(contents)
    print("Created .env with a generated database password; no password was printed.")


if __name__ == "__main__":
    main()
