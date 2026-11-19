"""Webhooks listener for real-time synchronization from Jira and GitHub into pgvector."""

import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from app.api.deps import SessionDep
from app.core.config import get_settings
from app.services.vector_service import vector_service

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

TICKET_KEY_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-[0-9]+)\b")


def verify_github_signature(raw_body: bytes, signature_header: str | None, secret: str) -> None:
    """Validate GitHub HMAC-SHA256 signature to prevent webhook forgery and cache poisoning."""
    if not secret:
        return

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing GitHub webhook signature header (X-Hub-Signature-256)",
        )

    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub webhook signature format",
        )

    expected_mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided_mac = signature_header.removeprefix("sha256=")
    if not secrets.compare_digest(expected_mac, provided_mac):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub webhook signature",
        )


def verify_jira_secret(request: Request, secret: str) -> None:
    """Validate Jira webhook shared secret to prevent unauthorized ticket vector injection."""
    if not secret:
        return

    header_secret = request.headers.get("X-Atlassian-Webhook-Secret")
    query_secret = request.query_params.get("secret")
    provided = header_secret or query_secret

    if not provided or not secrets.compare_digest(provided, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Jira webhook secret",
        )


@router.post(
    "/jira",
    status_code=status.HTTP_200_OK,
    summary="Jira Cloud Webhook Listener",
    description="Listen to Jira issue events and asynchronously synchronize embeddings in pgvector.",
)
async def jira_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> dict[str, str]:
    verify_jira_secret(request, settings.JIRA_WEBHOOK_SECRET)

    try:
        payload: dict[str, Any] = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload") from exc

    webhook_event = payload.get("webhookEvent", "")
    issue = payload.get("issue", {})
    if not issue or not issue.get("key"):
        return {"status": "ignored", "reason": "No issue found in payload"}

    issue_key = issue["key"]
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = str(fields.get("description") or "")
    status_name = fields.get("status", {}).get("name", "Unknown")
    assignee = fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None
    project_key = issue_key.split("-")[0]

    logger.info("Received Jira webhook event '%s' for issue %s", webhook_event, issue_key)

    # Upsert vector in background
    await vector_service.upsert_ticket_vector(
        session=session,
        issue_key=issue_key,
        project_key=project_key,
        summary=summary,
        description=description,
        status=status_name,
        assignee=assignee,
    )

    return {"status": "success", "message": f"Processed Jira event for {issue_key}"}


@router.post(
    "/github",
    status_code=status.HTTP_200_OK,
    summary="GitHub Webhook Listener",
    description="Listen to GitHub pull request merge events and link code diffs to Jira tickets in pgvector.",
)
async def github_webhook(
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    verify_github_signature(raw_body, signature, settings.GITHUB_WEBHOOK_SECRET)

    event_type = request.headers.get("X-GitHub-Event", "")
    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload") from exc

    if event_type == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        is_merged = pr.get("merged", False)

        if action == "closed" and is_merged:
            title = pr.get("title", "")
            body = pr.get("body", "")
            pr_number = pr.get("number")
            diff_text = f"PR #{pr_number}: {title}\nSummary: {body[:500]}"

            # Detect referenced Jira ticket keys
            referenced_keys = list(dict.fromkeys(TICKET_KEY_REGEX.findall(f"{title} {body}")))
            logger.info("GitHub PR #%s merged with referenced Jira keys: %s", pr_number, referenced_keys)

            for key in referenced_keys:
                proj_prefix = key.split("-")[0]
                await vector_service.upsert_ticket_vector(
                    session=session,
                    issue_key=key,
                    project_key=proj_prefix,
                    summary=f"Linked to PR #{pr_number}: {title}",
                    description=body,
                    status="Merged",
                    linked_pr_numbers=[pr_number],
                    code_diff_summary=diff_text,
                )
            return {"status": "success", "linked_tickets": referenced_keys}

    return {"status": "ignored", "reason": f"Event '{event_type}' not processed"}
