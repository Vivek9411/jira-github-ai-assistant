"""Webhooks listener for real-time synchronization from Jira and GitHub into pgvector."""

import re
import logging
from typing import Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from app.api.deps import SessionDep
from app.services.vector_service import vector_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

TICKET_KEY_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-[0-9]+)\b")


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
    payload: dict[str, Any] = await request.json()
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
) -> dict[str, str]:
    event_type = request.headers.get("X-GitHub-Event", "")
    payload: dict[str, Any] = await request.json()

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
            logger.info("GitHub PR #%d merged with referenced Jira keys: %s", pr_number, referenced_keys)

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
