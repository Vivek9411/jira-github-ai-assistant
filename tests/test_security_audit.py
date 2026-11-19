"""Automated Security Tests verifying vulnerability fixes and security invariants."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token
from app.main import app
from app.models.user import User
from app.services.auth_service import (
    InactiveAccountError,
    InvalidCredentialsError,
    RateLimitExceededError,
    auth_service,
)
from app.services.jira_client import JiraClientError, validate_jira_domain
from app.services.text_to_jql import text_to_jql_service

settings = get_settings()


# =========================================================================
# 1. CORS & Cross-Origin Security Tests
# =========================================================================

@pytest.mark.asyncio
async def test_cors_rejects_arbitrary_unauthorized_origin() -> None:
    """Verify that an unauthorized origin (e.g. https://evil.com) is not reflected with credentials."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/integrations/status",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        allow_origin = resp.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil.com"
        assert allow_origin != "*"


@pytest.mark.asyncio
async def test_cors_allows_configured_whitelisted_origin() -> None:
    """Verify that an authorized client origin is allowed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/api/v1/integrations/status",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert resp.headers.get("access-control-allow-credentials") == "true"


# =========================================================================
# 2. SSRF & Domain Validation Tests
# =========================================================================

def test_jira_domain_validation_blocks_ssrf_and_ip_addresses() -> None:
    """Verify that private IP addresses, loopback, link-local, and cloud metadata are blocked."""
    prohibited_domains = [
        "169.254.169.254",       # AWS/GCP Metadata endpoint
        "127.0.0.1",             # Localhost IPv4
        "::1",                   # Localhost IPv6
        "10.0.0.1",              # RFC 1918 Private class A
        "192.168.1.1",           # RFC 1918 Private class C
        "172.16.0.1",            # RFC 1918 Private class B
        "localhost",             # Local hostname
        "evil-attacker.com",     # Third party non-Atlassian domain
        "attacker.atlassian.net.attacker.com", # Subdomain deception
    ]

    for host in prohibited_domains:
        with pytest.raises(JiraClientError) as exc_info:
            validate_jira_domain(host)
        assert "not permitted" in str(exc_info.value) or "Invalid Jira domain" in str(exc_info.value)


def test_jira_domain_validation_permits_valid_cloud_domains() -> None:
    """Verify that legitimate Atlassian Cloud domains pass validation."""
    valid_domains = [
        "acme.atlassian.net",
        "my-team-123.atlassian.net",
        "company.jira.com",
        "https://enterprise.atlassian.net/",
    ]
    for d in valid_domains:
        clean = validate_jira_domain(d)
        assert "atlassian.net" in clean or "jira.com" in clean


# =========================================================================
# 3. Webhook Integrity & Signature Verification Tests
# =========================================================================

@pytest.mark.asyncio
async def test_github_webhook_rejects_missing_signature_when_secret_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that GitHub webhook enforces signature check when secret is configured."""
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "super_secret_github_webhook_key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/webhooks/github",
            headers={"X-GitHub-Event": "pull_request"},
            json={"action": "closed", "pull_request": {"merged": True, "title": "test", "number": 1}},
        )
        assert resp.status_code == 401
        assert "Missing GitHub webhook signature" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_github_webhook_rejects_forged_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that GitHub webhook rejects tampered/forged signatures."""
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "super_secret_github_webhook_key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            },
            json={"action": "closed", "pull_request": {"merged": True, "title": "forged", "number": 1}},
        )
        assert resp.status_code == 401
        assert "Invalid GitHub webhook signature" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_jira_webhook_rejects_unauthorized_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that Jira webhook rejects requests with invalid shared secret."""
    monkeypatch.setattr(settings, "JIRA_WEBHOOK_SECRET", "jira_secret_token_abc")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/webhooks/jira",
            headers={"X-Atlassian-Webhook-Secret": "wrong_secret"},
            json={"webhookEvent": "jira:issue_updated", "issue": {"key": "ENG-1"}},
        )
        assert resp.status_code == 401
        assert "Invalid Jira webhook secret" in resp.json()["detail"]


# =========================================================================
# 4. Authentication, Inactive Accounts & Rate Limiting Tests
# =========================================================================

@pytest.mark.asyncio
async def test_otp_rate_limiting_prevents_request_flooding() -> None:
    """Verify that rapid consecutive OTP requests for the same email trigger RateLimitExceededError."""
    test_email = "flood_test_user@example.com"
    auth_service._rate_limit_history.clear()

    # First request check passes
    auth_service._check_rate_limit(test_email)

    # Immediate second request should be blocked by cooldown
    with pytest.raises(RateLimitExceededError) as exc_info:
        auth_service._check_rate_limit(test_email)
    assert "Please wait" in str(exc_info.value)


@pytest.mark.asyncio
async def test_refresh_token_handles_invalid_or_expired_tokens_cleanly() -> None:
    """Verify that invalid refresh tokens return 401 Unauthorized without crashing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "tampered.jwt.token"})
        assert resp.status_code == 401
        assert "Invalid authentication token" in resp.json()["detail"] or "Invalid" in resp.json()["detail"]


# =========================================================================
# 5. JQL Query Injection Prevention Tests
# =========================================================================

def test_jql_injection_via_default_project_key_is_blocked() -> None:
    """Verify that malicious project key strings containing quotes or JQL syntax are sanitized."""
    malicious_inputs = [
        'ENG" OR 1=1 --',
        'PROJ" AND statusCategory = Done',
        'ACME; DROP TABLE users',
    ]

    for malicious in malicious_inputs:
        jql = text_to_jql_service.translate("What tickets are assigned to me?", default_project_key=malicious)
        # Should NOT contain unescaped malicious syntax
        assert malicious not in jql
        assert 'project = "' + malicious + '"' not in jql
