"""Explicit local setup: generate signing keys and create users after migrations."""

import argparse
import asyncio
import getpass
import os
import sys
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import Database
from app.core.security import password_hasher
from app.models.auth import LocalUser
from app.repositories.auth import AuthRepository
from app.schemas.auth import LoginInput


def init_keys(settings: Settings) -> bool:
    """Write a new pair with exclusive creation; never replace existing signing keys."""
    private_path, public_path = settings.jwt_private_key_path, settings.jwt_public_key_path
    if private_path.exists() and public_path.exists():
        print("Signing keys already exist; unchanged.")
        return False
    if private_path.exists() or public_path.exists() or private_path == public_path:
        raise ValueError("Incomplete key pair or duplicate paths; resolve before initialization")
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    public_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_bytes = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(private_bytes)
    with public_path.open("xb") as output:
        output.write(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
    print("Signing keys created. Keep the private key outside Git.")
    return True


async def create_user(
    settings: Settings, username: str, name: str, password: str, *, admin: bool
) -> bool:
    """Return False for an existing username without changing credentials or roles."""
    parsed = LoginInput(username=username, password=password)
    if len(password) < 12 or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Password must contain 12–128 characters; name must contain 1–100")
    database = Database(settings)
    try:
        async with database.sessions() as session, session.begin():
            if await AuthRepository(session).user_by_name(parsed.username.lower()):
                print("User already exists; credentials and roles unchanged.")
                return False
            encoded = await asyncio.to_thread(password_hasher.hash, password)
            session.add(
                LocalUser(
                    user_id=str(uuid4()),
                    username=parsed.username.lower(),
                    name=name.strip(),
                    password_hash=encoded,
                    is_admin=admin,
                    is_active=True,
                    create_by="bootstrap",
                    update_by="bootstrap",
                )
            )
        print("Local user created.")
        return True
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-keys", help="Generate RSA keys without overwriting existing files")
    user = commands.add_parser(
        "create-user", help="Create a local user without changing existing users"
    )
    user.add_argument("--username", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.command == "init-keys":
            init_keys(settings)
        else:
            password = os.environ.get("OLIXOPS_BOOTSTRAP_PASSWORD")
            if password is None:
                password = getpass.getpass("New user password (12–128 characters): ")
                if password != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords do not match")
            asyncio.run(create_user(settings, args.username, args.name, password, admin=args.admin))
    except OSError, ValueError, ValidationError, SQLAlchemyError:
        # Exception messages can contain the DSN or credential input; never print them.
        print(
            "Setup failed. Check configuration, key paths, input and database migrations.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
