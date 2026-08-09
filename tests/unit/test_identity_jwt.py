from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.identity import AuthenticationError, JWTAuthenticator
from nvidia_agentic_rag.security import DataClassification


def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        nvidia_api_key=SecretStr("test-key"),
        data_dir=tmp_path / "data",
        course_data_dir=tmp_path / "data/course",
        papers_data_dir=tmp_path / "data/papers",
        storage_dir=tmp_path / "storage",
        auth_mode="jwt",
        jwt_hs256_secret=SecretStr("secret-1234567890-secret-1234567890"),
        jwt_algorithms=("HS256",),
        jwt_issuer="issuer",
        jwt_audience="audience",
        _env_file=None,
    )


def token(secret="secret-1234567890-secret-1234567890", **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["architect"],
        "departments": ["platform"],
        "clearance": "confidential",
        "authz_version": "4",
        "iss": "issuer",
        "aud": "audience",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_authenticator_maps_verified_claims(tmp_path) -> None:
    identity = JWTAuthenticator(settings(tmp_path)).authenticate(token())
    assert identity.user_id == "user-1"
    assert identity.tenant_id == "tenant-a"
    assert identity.clearance == DataClassification.CONFIDENTIAL
    assert identity.roles == ("architect",)


def test_authenticator_rejects_invalid_token_and_missing_tenant(tmp_path) -> None:
    authenticator = JWTAuthenticator(settings(tmp_path))
    with pytest.raises(AuthenticationError):
        authenticator.authenticate(token(secret="wrong-secret-wrong-secret-wrong-secret"))
    with pytest.raises(AuthenticationError):
        authenticator.authenticate(token(tenant_id=""))
