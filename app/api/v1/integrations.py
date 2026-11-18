"""Integrations management endpoints for Jira and GitHub credentials."""

from typing import Any
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from app.api.deps import CurrentUserDep, SessionDep
from app.core.vault import default_token_vault
from app.models.integration import UserIntegration
from app.schemas.integration import (
    GitHubConnectIn,
    IntegrationStatusResponse,
    JiraConnectIn,
)
from app.services.github_client import GitHubAuthError, GitHubClient, GitHubClientError
from app.services.jira_client import JiraAuthenticationError, JiraClient, JiraClientError

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.post(
    "/validate-jira",
    status_code=status.HTTP_200_OK,
    summary="Validate Jira Credentials (Stateless)",
    description="Validate Atlassian Jira credentials directly against Jira Cloud without storing in database.",
)
async def validate_jira_credentials(
    payload: JiraConnectIn,
    current_user: CurrentUserDep,
) -> dict[str, Any]:
    """Test Jira credentials on the fly for client-side storage (Zero-Knowledge BYOK)."""
    client = JiraClient(domain=payload.domain, email=payload.email, api_token=payload.api_token)
    try:
        user_info = await client.validate_connection()
        return {
            "valid": True,
            "domain": client.domain,
            "display_name": user_info.get("displayName"),
            "email": payload.email.strip(),
            "account_id": user_info.get("accountId"),
            "message": f"Successfully verified Jira Cloud account for '{user_info.get('displayName')}'",
        }
    except JiraAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jira authentication failed. Please verify domain, email, and API token: {str(exc)}",
        ) from exc
    except JiraClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Jira server: {str(exc)}",
        ) from exc


@router.post(
    "/validate-github",
    status_code=status.HTTP_200_OK,
    summary="Validate GitHub Token (Stateless)",
    description="Validate GitHub PAT token directly against GitHub GraphQL API without storing in database.",
)
async def validate_github_token(
    payload: GitHubConnectIn,
    current_user: CurrentUserDep,
) -> dict[str, Any]:
    """Test GitHub token on the fly for client-side storage (Zero-Knowledge BYOK)."""
    client = GitHubClient(token=payload.personal_access_token)
    try:
        viewer = await client.validate_token()
        return {
            "valid": True,
            "login": viewer.get("login"),
            "name": viewer.get("name"),
            "url": viewer.get("url"),
            "message": f"Successfully verified GitHub account for user '{viewer.get('login')}'",
        }
    except GitHubAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub Personal Access Token: {str(exc)}",
        ) from exc
    except GitHubClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach GitHub API: {str(exc)}",
        ) from exc


@router.post(
    "/jira",
    status_code=status.HTTP_200_OK,
    summary="Connect Atlassian Jira",
    description="Validate Jira API credentials, encrypt token at rest, and persist integration.",
)
async def connect_jira(
    payload: JiraConnectIn,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    # 1. Validate connection with Jira Cloud
    client = JiraClient(domain=payload.domain, email=payload.email, api_token=payload.api_token)
    try:
        user_info = await client.validate_connection()
    except JiraAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jira authentication failed. Please verify domain, email, and API token: {str(exc)}",
        ) from exc
    except JiraClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Jira server: {str(exc)}",
        ) from exc

    # 2. Encrypt token via Fernet
    encrypted_token = default_token_vault.encrypt(payload.api_token.strip())

    # 3. Upsert integration record
    query = select(UserIntegration).where(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == "jira",
    )
    result = await session.execute(query)
    integration = result.scalar_one_or_none()

    if not integration:
        integration = UserIntegration(
            user_id=current_user.id,
            provider="jira",
            encrypted_token=encrypted_token,
            base_url=client.domain,
            account_email=payload.email.strip(),
            extra_metadata={"display_name": user_info.get("displayName"), "account_id": user_info.get("accountId")},
        )
        session.add(integration)
    else:
        integration.encrypted_token = encrypted_token
        integration.base_url = client.domain
        integration.account_email = payload.email.strip()
        integration.extra_metadata = {"display_name": user_info.get("displayName"), "account_id": user_info.get("accountId")}

    await session.commit()
    return {"message": f"Successfully connected Jira Cloud account for '{user_info.get('displayName')}'"}


@router.post(
    "/github",
    status_code=status.HTTP_200_OK,
    summary="Connect GitHub Account",
    description="Validate GitHub PAT token via GraphQL viewer query, encrypt at rest, and persist.",
)
async def connect_github(
    payload: GitHubConnectIn,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    # 1. Validate token with GitHub GraphQL API
    client = GitHubClient(token=payload.personal_access_token)
    try:
        viewer = await client.validate_token()
    except GitHubAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub Personal Access Token: {str(exc)}",
        ) from exc
    except GitHubClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach GitHub API: {str(exc)}",
        ) from exc

    # 2. Encrypt token via Fernet
    encrypted_token = default_token_vault.encrypt(payload.personal_access_token.strip())

    # 3. Upsert integration record
    query = select(UserIntegration).where(
        UserIntegration.user_id == current_user.id,
        UserIntegration.provider == "github",
    )
    result = await session.execute(query)
    integration = result.scalar_one_or_none()

    if not integration:
        integration = UserIntegration(
            user_id=current_user.id,
            provider="github",
            encrypted_token=encrypted_token,
            base_url="api.github.com",
            account_email=viewer.get("login"),
            extra_metadata={"login": viewer.get("login"), "name": viewer.get("name"), "url": viewer.get("url")},
        )
        session.add(integration)
    else:
        integration.encrypted_token = encrypted_token
        integration.account_email = viewer.get("login")
        integration.extra_metadata = {"login": viewer.get("login"), "name": viewer.get("name"), "url": viewer.get("url")}

    await session.commit()
    return {"message": f"Successfully connected GitHub account for user '{viewer.get('login')}'"}


@router.get(
    "/status",
    response_model=IntegrationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Integrations Status",
    description="Return connection status for Jira and GitHub without exposing secrets.",
)
async def get_integrations_status(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> IntegrationStatusResponse:
    query = select(UserIntegration).where(UserIntegration.user_id == current_user.id)
    result = await session.execute(query)
    integrations = {item.provider: item for item in result.scalars().all()}

    jira_item = integrations.get("jira")
    gh_item = integrations.get("github")

    return IntegrationStatusResponse(
        jira_connected=jira_item is not None,
        jira_domain=jira_item.base_url if jira_item else None,
        github_connected=gh_item is not None,
    )
