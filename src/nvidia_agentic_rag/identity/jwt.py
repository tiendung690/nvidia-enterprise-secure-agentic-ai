from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.identity.models import IdentityContext
from nvidia_agentic_rag.security.classification import DataClassification


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JWTAuthenticator:
    settings: Settings

    def _decode(self, token: str) -> dict[str, Any]:
        algorithms = list(self.settings.jwt_algorithms)
        options = {"require": ["exp", "sub"]}
        kwargs: dict[str, Any] = {
            "algorithms": algorithms,
            "audience": self.settings.jwt_audience or None,
            "issuer": self.settings.jwt_issuer or None,
            "options": options,
            "leeway": self.settings.jwt_clock_skew_seconds,
        }
        try:
            if self.settings.jwt_jwks_url:
                signing_key = jwt.PyJWKClient(self.settings.jwt_jwks_url).get_signing_key_from_jwt(
                    token
                )
                return jwt.decode(token, signing_key.key, **kwargs)
            secret = self.settings.jwt_hs256_secret_value()
            if not secret:
                raise AuthenticationError(
                    "JWT_JWKS_URL or JWT_HS256_SECRET must be configured in jwt mode"
                )
            return jwt.decode(token, secret, **kwargs)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("Bearer token validation failed") from exc

    def authenticate(self, token: str) -> IdentityContext:
        claims = self._decode(token)
        tenant_id = str(claims.get(self.settings.jwt_tenant_claim, "")).strip()
        if not tenant_id:
            raise AuthenticationError("Verified token does not contain a tenant claim")

        roles = claims.get(self.settings.jwt_roles_claim, [])
        departments = claims.get(self.settings.jwt_departments_claim, [])
        clearance_raw = claims.get(
            self.settings.jwt_clearance_claim,
            self.settings.default_clearance,
        )
        authz_version = str(
            claims.get(self.settings.jwt_authorization_version_claim, "1")
        )
        try:
            clearance = DataClassification.parse(clearance_raw)
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Invalid clearance claim") from exc

        return IdentityContext(
            user_id=str(claims["sub"]),
            tenant_id=tenant_id,
            roles=roles,
            departments=departments,
            clearance=clearance,
            authorization_version=authz_version,
            token_id=str(claims.get("jti")) if claims.get("jti") else None,
            claims=claims,
        )
