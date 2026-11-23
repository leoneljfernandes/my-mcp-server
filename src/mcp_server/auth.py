"""Constant-time Bearer token authentication for FastMCP v4."""

from __future__ import annotations

import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier


class ConstantTimeBearerVerifier(TokenVerifier):
    """Validates a static Bearer token using constant-time comparison (`hmac.compare_digest`).

    Never logs or exposes the configured secret token.
    """

    def __init__(self, expected_token: str, *, client_id: str = "devteam-mcp-client") -> None:
        super().__init__()
        if not expected_token:
            raise ValueError("expected_token must not be empty")
        self._expected_bytes = expected_token.encode("utf-8")
        self._client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        candidate_bytes = token.encode("utf-8")
        if not hmac.compare_digest(candidate_bytes, self._expected_bytes):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=["skills:read"],
        )
