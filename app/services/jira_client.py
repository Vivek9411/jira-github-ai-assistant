"""Asynchronous Jira REST API client for ticket operations and JQL execution."""

import base64
import ipaddress
import logging
import re
from typing import Any
import httpx

logger = logging.getLogger(__name__)

JIRA_DOMAIN_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9][-a-zA-Z0-9]{0,62}\.)+(?:atlassian\.net|jira\.com)$",
    re.IGNORECASE,
)


def validate_jira_domain(domain: str) -> str:
    """Validate and sanitize Jira Cloud domain, blocking SSRF and internal network probing."""
    if not domain or not isinstance(domain, str):
        raise JiraClientError("Jira domain cannot be empty")

    clean_domain = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    host_only = clean_domain.split("/")[0].split(":")[0]

    # Block IP addresses (private, loopback, link-local, cloud metadata)
    try:
        ip = ipaddress.ip_address(host_only)
        raise JiraClientError(f"Prohibited Jira host: direct IP addresses are not permitted ({host_only})")
    except ValueError:
        pass  # Not a raw IP, proceed to domain regex

    if not JIRA_DOMAIN_REGEX.match(host_only):
        raise JiraClientError(
            f"Invalid Jira domain '{clean_domain}'. Only official Atlassian Cloud domains (*.atlassian.net, *.jira.com) are permitted."
        )

    return clean_domain


class JiraClientError(Exception):
    """Base exception for Jira client operations."""
    pass


class JiraAuthenticationError(JiraClientError):
    """Raised when Jira credentials or permissions are invalid (401/403)."""
    pass


class JiraNotFoundError(JiraClientError):
    """Raised when an issue or project is not found (404)."""
    pass


class JiraOperationError(JiraClientError):
    """Raised when Jira rejects an operation or transition (400/422)."""
    pass


class JiraClient:
    """Asynchronous client interacting directly with Atlassian Jira Cloud REST API v3."""

    def __init__(self, domain: str, email: str, api_token: str) -> None:
        clean_domain = validate_jira_domain(domain)
        self.base_url = f"https://{clean_domain}/rest/api/3"
        self.domain = clean_domain

        auth_string = f"{email.strip()}:{api_token.strip()}"
        encoded_auth = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Validate response status and return parsed JSON."""
        if response.status_code in (401, 403):
            raise JiraAuthenticationError(f"Jira authentication failed ({response.status_code}): {response.text}")
        if response.status_code == 404:
            raise JiraNotFoundError("Requested Jira resource not found")
        if response.status_code in (400, 422):
            raise JiraOperationError(f"Jira validation error: {response.text}")
        if not response.is_success:
            raise JiraClientError(f"Jira API request failed with status {response.status_code}: {response.text}")

        if response.status_code == 204:
            return {}
        return response.json()

    async def validate_connection(self) -> dict[str, Any]:
        """Verify credential validity against Jira Cloud."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/myself", headers=self.headers)
                return await self._handle_response(response)
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error connecting to Jira: {str(exc)}") from exc

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch detailed information for a single Jira issue."""
        url = f"{self.base_url}/issue/{issue_key.upper()}"
        params = {
            "fields": "summary,description,status,assignee,priority,issuetype,created,updated,issuelinks,subtasks,comment",
            "expand": "renderedFields",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=self.headers, params=params)
                data = await self._handle_response(response)
                fields = data.get("fields", {})

                # Extract issue links / blockers
                linked_issues = []
                for link in fields.get("issuelinks", []):
                    if "outwardIssue" in link:
                        linked_issues.append({
                            "type": link.get("type", {}).get("outward"),
                            "key": link["outwardIssue"].get("key"),
                            "summary": link["outwardIssue"].get("fields", {}).get("summary"),
                            "status": link["outwardIssue"].get("fields", {}).get("status", {}).get("name"),
                        })
                    elif "inwardIssue" in link:
                        linked_issues.append({
                            "type": link.get("type", {}).get("inward"),
                            "key": link["inwardIssue"].get("key"),
                            "summary": link["inwardIssue"].get("fields", {}).get("summary"),
                            "status": link["inwardIssue"].get("fields", {}).get("status", {}).get("name"),
                        })

                # Extract subtasks
                subtasks = [
                    {
                        "key": st.get("key"),
                        "summary": st.get("fields", {}).get("summary"),
                        "status": st.get("fields", {}).get("status", {}).get("name"),
                    }
                    for st in fields.get("subtasks", [])
                ]

                return {
                    "key": data.get("key"),
                    "summary": fields.get("summary"),
                    "status": fields.get("status", {}).get("name"),
                    "status_category": fields.get("status", {}).get("statusCategory", {}).get("name"),
                    "assignee": fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
                    "priority": fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None",
                    "issue_type": fields.get("issuetype", {}).get("name"),
                    "description": data.get("renderedFields", {}).get("description") or str(fields.get("description") or ""),
                    "created": fields.get("created"),
                    "updated": fields.get("updated"),
                    "linked_issues": linked_issues,
                    "subtasks": subtasks,
                }
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error querying Jira: {str(exc)}") from exc

    async def search_issues(self, jql: str, limit: int = 15) -> list[dict[str, Any]]:
        """Execute a JQL query to retrieve a batch of matching issues."""
        url = f"{self.base_url}/search"
        payload = {
            "jql": jql,
            "maxResults": limit,
            "fields": ["summary", "status", "assignee", "priority", "issuetype", "updated"],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                data = await self._handle_response(response)
                issues = []
                for item in data.get("issues", []):
                    f = item.get("fields", {})
                    issues.append({
                        "key": item.get("key"),
                        "summary": f.get("summary"),
                        "status": f.get("status", {}).get("name"),
                        "status_category": f.get("status", {}).get("statusCategory", {}).get("name"),
                        "assignee": f.get("assignee", {}).get("displayName", "Unassigned") if f.get("assignee") else "Unassigned",
                        "priority": f.get("priority", {}).get("name", "None") if f.get("priority") else "None",
                        "issue_type": f.get("issuetype", {}).get("name"),
                        "updated": f.get("updated"),
                    })
                return issues
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error executing JQL: {str(exc)}") from exc

    async def get_transitions(self, issue_key: str) -> list[dict[str, str]]:
        """Discover available workflow transitions for an issue (e.g. In Progress, Done, Closed)."""
        url = f"{self.base_url}/issue/{issue_key.upper()}/transitions"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url, headers=self.headers)
                data = await self._handle_response(response)
                return [
                    {"id": t["id"], "name": t["name"], "to_status": t["to"]["name"]}
                    for t in data.get("transitions", [])
                ]
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error fetching transitions: {str(exc)}") from exc

    async def transition_issue(self, issue_key: str, target_status_or_id: str) -> dict[str, str]:
        """Move issue to a new status (e.g. 'Done' or specific transition ID)."""
        available = await self.get_transitions(issue_key)
        target_id: str | None = None

        # Check by ID first, then by case-insensitive name
        for t in available:
            if t["id"] == target_status_or_id or t["name"].lower() == target_status_or_id.lower() or t["to_status"].lower() == target_status_or_id.lower():
                target_id = t["id"]
                target_name = t["name"]
                break

        if not target_id:
            valid_names = ", ".join([f"'{t['name']}'" for t in available])
            raise JiraOperationError(f"Invalid transition '{target_status_or_id}'. Available transitions: {valid_names}")

        url = f"{self.base_url}/issue/{issue_key.upper()}/transitions"
        payload = {"transition": {"id": target_id}}

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                await self._handle_response(response)
                return {"message": f"Successfully transitioned {issue_key.upper()} to '{target_name}'", "transition_id": target_id}
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error executing transition: {str(exc)}") from exc

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
    ) -> dict[str, Any]:
        """Create a new Jira issue in the specified project."""
        url = f"{self.base_url}/issue"
        # Jira Cloud API v3 accepts Atlassian Document Format (ADF) or simple description text
        payload = {
            "fields": {
                "project": {"key": project_key.upper()},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description or "No description provided."}],
                        }
                    ],
                },
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                data = await self._handle_response(response)
                return {
                    "id": data.get("id"),
                    "key": data.get("key"),
                    "self": data.get("self"),
                    "url": f"https://{self.domain}/browse/{data.get('key')}",
                }
            except httpx.RequestError as exc:
                raise JiraClientError(f"Network error creating Jira issue: {str(exc)}") from exc
