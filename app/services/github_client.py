"""Asynchronous GitHub GraphQL v4 and REST client for single-roundtrip context fetching."""

import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """Base exception for GitHub client operations."""
    pass


class GitHubAuthError(GitHubClientError):
    """Raised when GitHub token is invalid or expired."""
    pass


class GitHubNotFoundError(GitHubClientError):
    """Raised when a repository, PR, or commit is not found."""
    pass


class GitHubClient:
    """Asynchronous client interacting with GitHub GraphQL v4 API with single-roundtrip queries."""

    GRAPHQL_URL = "https://api.github.com/graphql"
    REST_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        clean_token = token.strip()
        self.headers = {
            "Authorization": f"Bearer {clean_token}",
            "Accept": "application/vnd.github.v4+json",
            "User-Agent": "Jira-GitHub-AI-Assistant",
        }

    async def _post_graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query against GitHub v4 API."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.post(
                    self.GRAPHQL_URL,
                    headers=self.headers,
                    json={"query": query, "variables": variables or {}},
                )
                if response.status_code in (401, 403):
                    raise GitHubAuthError(f"GitHub authentication error ({response.status_code}): {response.text}")
                if not response.is_success:
                    raise GitHubClientError(f"GitHub request failed ({response.status_code}): {response.text}")

                data = response.json()
                if "errors" in data:
                    err_msg = "; ".join([e.get("message", "Unknown error") for e in data["errors"]])
                    logger.warning("GitHub GraphQL errors: %s", err_msg)
                    if any("Could not resolve to a Repository" in e.get("message", "") for e in data["errors"]):
                        raise GitHubNotFoundError(err_msg)
                    raise GitHubClientError(err_msg)

                return data.get("data", {})
            except httpx.RequestError as exc:
                raise GitHubClientError(f"Network error querying GitHub: {str(exc)}") from exc

    async def validate_token(self) -> dict[str, Any]:
        """Verify GitHub Personal Access Token validity."""
        query = """
        query CheckViewer {
            viewer {
                login
                name
                url
            }
        }
        """
        data = await self._post_graphql(query)
        return data.get("viewer", {})

    async def get_pull_request_context(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Fetch PR status, reviews, changed files, and linked commits in a single GraphQL network roundtrip."""
        query = """
        query GetPRDetails($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                pullRequest(number: $number) {
                    title
                    body
                    state
                    isDraft
                    merged
                    mergedAt
                    url
                    author {
                        login
                    }
                    files(first: 15) {
                        nodes {
                            path
                            additions
                            deletions
                            changeType
                        }
                    }
                    commits(last: 10) {
                        nodes {
                            commit {
                                oid
                                messageHeadline
                                messageBody
                                author {
                                    name
                                    date
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        variables = {"owner": owner, "repo": repo, "number": pr_number}
        data = await self._post_graphql(query, variables)
        repo_data = data.get("repository")
        if not repo_data or not repo_data.get("pullRequest"):
            raise GitHubNotFoundError(f"Pull request #{pr_number} not found in {owner}/{repo}")

        pr = repo_data["pullRequest"]
        files = [
            {
                "path": f["path"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "change_type": f["changeType"],
            }
            for f in pr.get("files", {}).get("nodes", [])
        ]
        commits = [
            {
                "sha": c["commit"]["oid"][:8],
                "headline": c["commit"]["messageHeadline"],
                "author": c["commit"].get("author", {}).get("name"),
                "date": c["commit"].get("author", {}).get("date"),
            }
            for c in pr.get("commits", {}).get("nodes", [])
        ]

        return {
            "number": pr_number,
            "title": pr.get("title"),
            "body": pr.get("body"),
            "state": pr.get("state"),
            "is_merged": pr.get("merged", False),
            "merged_at": pr.get("mergedAt"),
            "url": pr.get("url"),
            "author": pr.get("author", {}).get("login"),
            "files": files,
            "commits": commits,
        }

    async def search_issues_and_prs(self, repo_full_name: str, query_term: str) -> list[dict[str, Any]]:
        """Search repository PRs and issues referencing a specific ticket key or phrase."""
        search_query = f"repo:{repo_full_name} {query_term} is:pr"
        query = """
        query SearchRepoPRs($query: String!) {
            search(query: $query, type: ISSUE, first: 10) {
                nodes {
                    ... on PullRequest {
                        number
                        title
                        state
                        merged
                        url
                        author {
                            login
                        }
                        updatedAt
                    }
                }
            }
        }
        """
        data = await self._post_graphql(query, {"query": search_query})
        items = []
        for node in data.get("search", {}).get("nodes", []):
            if node:
                items.append({
                    "number": node.get("number"),
                    "title": node.get("title"),
                    "state": node.get("state"),
                    "is_merged": node.get("merged", False),
                    "url": node.get("url"),
                    "author": node.get("author", {}).get("login"),
                    "updated_at": node.get("updatedAt"),
                })
        return items
