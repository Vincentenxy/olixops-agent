"""RSA JWT and Argon2 primitives, independent of HTTP and persistence."""

import base64
import hashlib
import secrets
from datetime import timedelta
from functools import lru_cache
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.models.auth import utcnow
from app.schemas.auth import UserInfo

password_hasher = PasswordHasher()


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return password_hasher.hash(secrets.token_urlsafe(32))


def verify_password(encoded: str, supplied: str) -> bool:
    try:
        return password_hasher.verify(encoded, supplied)
    except VerificationError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Security:
    """Missing keys leave public health available; authentication fails closed with 503."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.private_key: rsa.RSAPrivateKey | None = None
        self.public_key: rsa.RSAPublicKey | None = None

    @property
    def ready(self) -> bool:
        return self.private_key is not None and self.public_key is not None

    def load(self) -> None:
        if not self.settings.jwt_private_key_path.is_file():
            return
        private = serialization.load_pem_private_key(
            self.settings.jwt_private_key_path.read_bytes(), password=None
        )
        if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 2048:
            raise ValueError("JWT signing key must be RSA with at least 2048 bits")
        if self.settings.jwt_public_key is not None:
            raw = self.settings.jwt_public_key.get_secret_value().encode()
        elif self.settings.jwt_public_key_path.is_file():
            raw = self.settings.jwt_public_key_path.read_bytes()
        else:
            raise ValueError("JWT public key is missing")
        public = (
            serialization.load_pem_public_key(raw)
            if raw.startswith(b"-----BEGIN")
            else serialization.load_der_public_key(base64.b64decode(raw, validate=True))
        )
        if not isinstance(public, rsa.RSAPublicKey) or (
            private.public_key().public_numbers() != public.public_numbers()
        ):
            raise ValueError("JWT public and private keys do not match")
        self.private_key, self.public_key = private, public
        dummy_password_hash()

    def issue(self, user: UserInfo, session_id: str) -> str:
        if self.private_key is None:
            raise RuntimeError("Authentication keys are unavailable")
        now = utcnow()
        return jwt.encode(
            {
                "sub": user.user_id,
                "staffuserid": user.user_id,
                "name": user.name,
                "sid": session_id,
                "jti": str(uuid4()),
                "iss": self.settings.jwt_issuer,
                "aud": self.settings.jwt_audience,
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(seconds=self.settings.access_token_seconds),
            },
            self.private_key,
            algorithm="RS256",
        )

    def decode(self, token: str) -> tuple[str, str]:
        if self.public_key is None:
            raise RuntimeError("Authentication keys are unavailable")
        claims = jwt.decode(
            token,
            self.public_key,
            algorithms=["RS256"],
            audience=self.settings.jwt_audience,
            issuer=self.settings.jwt_issuer,
            options={
                "require": [
                    "sub",
                    "staffuserid",
                    "name",
                    "sid",
                    "jti",
                    "iss",
                    "aud",
                    "iat",
                    "nbf",
                    "exp",
                ]
            },
        )
        for key in ("sub", "staffuserid", "name", "sid", "jti"):
            if not isinstance(claims[key], str) or not claims[key]:
                raise jwt.InvalidTokenError("Invalid required identity claim")
        if claims["sub"] != claims["staffuserid"]:
            raise jwt.InvalidTokenError("Inconsistent identity claims")
        user_id: str = claims["staffuserid"]
        session_id: str = claims["sid"]
        return user_id, session_id
