"""Agent orchestration service uniting Live Jira actions, GitHub GraphQL context, and Vector RAG."""

import re
import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.vault import default_token_vault
from app.models.integration import UserIntegration
from app.models.mapping import ProjectMapping
from app.models.user import User
from app.services.github_client import GitHubClient, GitHubClientError
from app.services.jira_client import JiraClient, JiraClientError
from app.services.text_to_jql import text_to_jql_service
from app.services.vector_service import vector_service

logger = logging.getLogger(__name__)


class AgentService:
    """Central AI assistant engine coordinating between Jira live APIs, GitHub GraphQL, and RAG."""

    CREATE_ISSUE_REGEX = re.compile(
        r"^(?:create|open|file)\s+(?:a\s+)?(?:new\s+)?(bug|task|story|issue)\s+(?:in\s+([A-Z0-9]+)\s*:?\s*)?(.*)",
        re.IGNORECASE | re.DOTALL,
    )
    TRANSITION_REGEX = re.compile(
        r"^(?:(?:mark|move|transition|set)\s+(?:ticket\s+|issue\s+)?([A-Z0-9]+-[0-9]+)\s+(?:as\s+|to\s+)?(done|closed|in progress|in review|to do))|(?:close\s+(?:ticket\s+|issue\s+)?([A-Z0-9]+-[0-9]+))",
        re.IGNORECASE,
    )

    async def get_user_clients(
        self, session: AsyncSession, user_id: Any
    ) -> tuple[JiraClient | None, GitHubClient | None]:
        """Retrieve and initialize authenticated Jira and GitHub clients using decrypted tokens."""
        query = select(UserIntegration).where(UserIntegration.user_id == user_id)
        result = await session.execute(query)
        integrations = {i.provider: i for i in result.scalars().all()}

        jira_client: JiraClient | None = None
        if "jira" in integrations:
            item = integrations["jira"]
            try:
                decrypted_token = default_token_vault.decrypt(item.encrypted_token)
                jira_client = JiraClient(
                    domain=item.base_url or "",
                    email=item.account_email or "",
                    api_token=decrypted_token,
                )
            except Exception as exc:
                logger.error("Failed to decrypt Jira token for user %s: %s", user_id, exc)

        github_client: GitHubClient | None = None
        if "github" in integrations:
            item = integrations["github"]
            try:
                decrypted_token = default_token_vault.decrypt(item.encrypted_token)
                github_client = GitHubClient(token=decrypted_token)
            except Exception as exc:
                logger.error("Failed to decrypt GitHub token for user %s: %s", user_id, exc)

        return jira_client, github_client

    async def get_user_repo_mapping(
        self, session: AsyncSession, user_id: Any, project_key: str
    ) -> str | None:
        """Find mapped GitHub repository (owner/repo) for a given Jira project key."""
        query = select(ProjectMapping).where(
            ProjectMapping.user_id == user_id,
            ProjectMapping.jira_project_key == project_key.upper(),
        )
        result = await session.execute(query)
        mapping = result.scalar_one_or_none()
        return mapping.github_repo if mapping else None

    async def process_user_message(
        self,
        session: AsyncSession,
        user: User,
        user_message: str,
    ) -> dict[str, Any]:
        """Process natural language request, execute appropriate tools, and return structured response."""
        clean_msg = user_message.strip()
        jira_client, github_client = await self.get_user_clients(session, user.id)

        # ---------------------------------------------------------
        # Branch 1: Mutative Action -> Transition / Close Issue
        # ---------------------------------------------------------
        transition_match = self.TRANSITION_REGEX.search(clean_msg)
        if transition_match:
            if not jira_client:
                return {
                    "response": "⚠️ Jira is not connected yet. Please connect your Jira account under Settings/Integrations first.",
                    "tool_calls": [],
                }
            if transition_match.group(1):
                issue_key = transition_match.group(1).upper()
                target_status = transition_match.group(2).title()
            else:
                issue_key = transition_match.group(3).upper()
                target_status = "Closed"
            try:
                result = await jira_client.transition_issue(issue_key, target_status)
                return {
                    "response": f"✅ {result['message']}",
                    "tool_calls": [{"tool": "jira_transition_issue", "args": {"issue_key": issue_key, "target_status": target_status}, "result": result}],
                }
            except JiraClientError as exc:
                return {
                    "response": f"❌ Could not transition ticket {issue_key}: {str(exc)}",
                    "tool_calls": [{"tool": "jira_transition_issue", "error": str(exc)}],
                }

        # ---------------------------------------------------------
        # Branch 2: Mutative Action -> Create New Issue
        # ---------------------------------------------------------
        create_match = self.CREATE_ISSUE_REGEX.search(clean_msg)
        if create_match and ("create" in clean_msg.lower() or "file" in clean_msg.lower()):
            if not jira_client:
                return {
                    "response": "⚠️ Jira is not connected yet. Please connect your Jira account to create tickets.",
                    "tool_calls": [],
                }
            raw_type = create_match.group(1).title()
            proj_key = create_match.group(2)
            content = create_match.group(3).strip()

            if not proj_key:
                # Attempt to extract project key from mapping or ticket key regex
                mappings_query = select(ProjectMapping).where(ProjectMapping.user_id == user.id).limit(1)
                mapping_res = await session.execute(mappings_query)
                default_mapping = mapping_res.scalar_one_or_none()
                proj_key = default_mapping.jira_project_key if default_mapping else "ENG"

            summary = content.splitlines()[0] if content else "New issue from AI assistant"
            description = "\n".join(content.splitlines()[1:]) if len(content.splitlines()) > 1 else "Created via AI Assistant chat."

            try:
                created = await jira_client.create_issue(
                    project_key=proj_key,
                    summary=summary,
                    description=description,
                    issue_type=raw_type if raw_type in ("Bug", "Task", "Story") else "Task",
                )
                return {
                    "response": f"🎉 Created new Jira {raw_type} **[{created['key']}]({created['url']})**: {summary}",
                    "tool_calls": [{"tool": "jira_create_issue", "args": {"project_key": proj_key, "summary": summary}, "result": created}],
                }
            except JiraClientError as exc:
                return {
                    "response": f"❌ Failed to create Jira ticket: {str(exc)}",
                    "tool_calls": [{"tool": "jira_create_issue", "error": str(exc)}],
                }

        # ---------------------------------------------------------
        # Branch 3: Deep Developer Inquiry / Historical Fix Retrieval (RAG + Code Context)
        # ---------------------------------------------------------
        is_dev_inquiry = any(term in clean_msg.lower() for term in ["how did", "fix done by", "what code changed", "show diff", "explain fix", "who fixed"])
        if is_dev_inquiry:
            # 1. Search semantic vector store
            similar_tickets = await vector_service.search_similar_tickets(session, clean_msg, limit=3)

            # 2. Extract ticket keys from query if explicit
            ticket_keys = text_to_jql_service.extract_ticket_keys(clean_msg)
            code_contexts = []

            # If GitHub is connected and we have a ticket, fetch linked PRs and commits
            if github_client and (ticket_keys or similar_tickets):
                target_key = ticket_keys[0] if ticket_keys else similar_tickets[0]["issue_key"]
                proj_prefix = target_key.split("-")[0]
                repo = await self.get_user_repo_mapping(session, user.id, proj_prefix)

                if repo:
                    try:
                        owner, repo_name = repo.split("/")
                        prs = await github_client.search_issues_and_prs(repo, target_key)
                        for pr in prs[:2]:
                            pr_context = await github_client.get_pull_request_context(owner, repo_name, pr["number"])
                            code_contexts.append(pr_context)
                    except Exception as exc:
                        logger.warning("Could not fetch GitHub PR context: %s", exc)

            response_lines = [
                f"### 🔍 Analysis for Developer Query: *\"{clean_msg}\"*\n",
            ]
            if similar_tickets:
                response_lines.append("**Relevant Historical Tickets Found:**")
                for st in similar_tickets:
                    response_lines.append(f"- **{st['issue_key']}**: {st['summary']} (Status: `{st['status']}`, Assignee: {st['assignee'] or 'None'})")
                    if st.get("code_diff_summary"):
                        response_lines.append(f"  > *Fix Summary:* {st['code_diff_summary'][:200]}...")

            if code_contexts:
                response_lines.append("\n**Linked GitHub Code Changes:**")
                for ctx in code_contexts:
                    response_lines.append(f"- **PR #{ctx['number']}**: [{ctx['title']}]({ctx['url']}) (Author: @{ctx['author']}, Merged: `{ctx['is_merged']}`)")
                    if ctx.get("files"):
                        changed_files = ", ".join([f"`{f['path']}`" for f in ctx["files"][:4]])
                        response_lines.append(f"  - Touched files: {changed_files}")
                    if ctx.get("commits"):
                        last_commit = ctx["commits"][0]
                        response_lines.append(f"  - Latest commit: `{last_commit['sha']}` - *{last_commit['headline']}*")

            if not similar_tickets and not code_contexts:
                response_lines.append("No historical fixes or code diffs were found matching your inquiry. You can sync tickets or connect repository mappings under Integrations.")

            return {
                "response": "\n".join(response_lines),
                "tool_calls": [
                    {"tool": "vector_rag_search", "result_count": len(similar_tickets)},
                    {"tool": "github_graphql_fetch", "pr_count": len(code_contexts)},
                ],
            }

        # ---------------------------------------------------------
        # Branch 4: Real-Time Live Status & Pending Tickets (Text-to-JQL)
        # ---------------------------------------------------------
        if jira_client:
            ticket_keys = text_to_jql_service.extract_ticket_keys(clean_msg)

            # Single ticket direct fetch
            if len(ticket_keys) == 1 and ("pending" not in clean_msg.lower() and "blocker" not in clean_msg.lower()):
                try:
                    issue = await jira_client.get_issue(ticket_keys[0])
                    lines = [
                        f"### 🎫 Issue Details: **{issue['key']}**",
                        f"- **Summary:** {issue['summary']}",
                        f"- **Status:** `{issue['status']}` ({issue['status_category']})",
                        f"- **Assignee:** {issue['assignee']}",
                        f"- **Priority:** {issue['priority']}",
                        f"- **Type:** {issue['issue_type']}",
                    ]
                    if issue.get("subtasks"):
                        lines.append("\n**Subtasks:**")
                        for st in issue["subtasks"]:
                            lines.append(f"  - [{st['key']}] {st['summary']} — `{st['status']}`")
                    if issue.get("linked_issues"):
                        lines.append("\n**Linked Issues & Blockers:**")
                        for li in issue["linked_issues"]:
                            lines.append(f"  - {li['type']}: [{li['key']}] {li['summary']} — `{li['status']}`")

                    return {
                        "response": "\n".join(lines),
                        "tool_calls": [{"tool": "jira_get_issue", "args": {"issue_key": ticket_keys[0]}, "result": issue}],
                    }
                except JiraClientError as exc:
                    return {
                        "response": f"⚠️ Could not fetch issue {ticket_keys[0]}: {str(exc)}",
                        "tool_calls": [{"tool": "jira_get_issue", "error": str(exc)}],
                    }

            # Multi-ticket or JQL search
            jql = text_to_jql_service.translate(clean_msg)
            try:
                issues = await jira_client.search_issues(jql, limit=10)
                if not issues:
                    return {
                        "response": f"No issues found matching query (JQL: `{jql}`).",
                        "tool_calls": [{"tool": "jira_search_issues", "args": {"jql": jql}, "count": 0}],
                    }

                lines = [f"Found **{len(issues)}** matching Jira issues (JQL: `{jql}`):\n"]
                for it in issues:
                    lines.append(f"- **{it['key']}**: {it['summary']} | Status: `{it['status']}` | Assignee: {it['assignee']} | Priority: {it['priority']}")
                return {
                    "response": "\n".join(lines),
                    "tool_calls": [{"tool": "jira_search_issues", "args": {"jql": jql}, "count": len(issues)}],
                }
            except JiraClientError as exc:
                return {
                    "response": f"⚠️ Jira query error: {str(exc)}",
                    "tool_calls": [{"tool": "jira_search_issues", "error": str(exc)}],
                }

        # Fallback if Jira is not connected
        return {
            "response": "Hello! I am your Jira-GitHub AI Assistant. To get live ticket updates, create tickets, or view code diffs, please connect your Jira and GitHub accounts via the `/api/v1/integrations` endpoints.",
            "tool_calls": [],
        }


agent_service = AgentService()
