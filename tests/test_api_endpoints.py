"""Integration tests for FastAPI application endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_health_check_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Jira-GitHub" in data["app"]


@pytest.mark.asyncio
async def test_serve_index_html() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Jira" in response.text and "GitHub" in response.text

        # Verify /login also serves the view
        login_resp = await client.get("/login")
        assert login_resp.status_code == 200
        assert "text/html" in login_resp.headers.get("content-type", "")
        assert "Sign In" in login_resp.text


@pytest.mark.asyncio
async def test_protected_routes_require_bearer_token() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Integrations status requires token
        resp_int = await client.get("/api/v1/integrations/status")
        assert resp_int.status_code in (401, 403)

        # Validate endpoints require token
        resp_val_jira = await client.post("/api/v1/integrations/validate-jira", json={"domain": "a.b", "email": "a@b.com", "api_token": "token12345"})
        assert resp_val_jira.status_code in (401, 403)

        resp_val_gh = await client.post("/api/v1/integrations/validate-github", json={"personal_access_token": "token12345"})
        assert resp_val_gh.status_code in (401, 403)

        # Chat message requires token
        resp_chat = await client.post("/api/v1/chat/message", json={"content": "Check ticket ENG-104"})
        assert resp_chat.status_code in (401, 403)

        # Mappings list requires token
        resp_map = await client.get("/api/v1/mappings")
        assert resp_map.status_code in (401, 403)


@pytest.mark.asyncio
async def test_chat_schema_accepts_client_credentials() -> None:
    """Verify that ChatMessageIn parses in-memory client credentials cleanly."""
    from app.schemas.chat import ChatMessageIn, ClientCredentials
    msg = ChatMessageIn(
        content="What is the status of ENG-104?",
        credentials=ClientCredentials(
            jira_domain="acme.atlassian.net",
            jira_email="alex@company.com",
            jira_token="secret_token_123",
            github_token="ghp_secret_456",
            github_repo="acme/api",
        )
    )
    assert msg.credentials is not None
    assert msg.credentials.jira_domain == "acme.atlassian.net"
    assert msg.credentials.github_repo == "acme/api"
