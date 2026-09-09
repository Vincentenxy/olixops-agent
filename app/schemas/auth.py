"""Browser authentication schemas; passwords are never represented as plain repr values."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserInfo(BaseModel):
    user_id: str
    username: str
    name: str
    is_admin: bool


class CurrentUser(UserInfo):
    session_id: str = Field(exclude=True, repr=False)
    jwt: str = Field(exclude=True, repr=False)
    cookie: str = Field(exclude=True, repr=False)


class TokenData(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserInfo
