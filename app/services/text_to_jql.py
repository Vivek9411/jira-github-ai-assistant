"""Text-to-JQL translation service for converting natural language queries into valid Jira JQL."""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TextToJQLService:
    """Translates natural language questions from PMs and Developers into precise Jira Query Language (JQL)."""

    TICKET_KEY_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-[0-9]+)\b")
    PROJECT_KEY_REGEX = re.compile(r"\b(?:in\s+project|project|in)\s+([A-Z][A-Z0-9]{1,9})\b", re.IGNORECASE)
    PROJECT_KEY_STRICT_REGEX = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

    def extract_ticket_keys(self, query: str) -> list[str]:
        """Extract all Jira issue keys (e.g. ENG-104, PROJ-23) present in text."""
        return list(dict.fromkeys(self.TICKET_KEY_REGEX.findall(query)))

    def extract_project_key(self, query: str, default: str | None = None) -> str | None:
        """Extract project key, ignoring common false positive English words and strictly validating fallback."""
        ignore_words = {"THE", "THIS", "A", "AN", "MY", "OUR", "ALL", "SOME", "ANY", "PROJECT", "ISSUE", "TICKET"}
        for match in self.PROJECT_KEY_REGEX.finditer(query):
            candidate = match.group(1).upper()
            if candidate not in ignore_words and len(candidate) >= 2:
                return candidate
        if default and self.PROJECT_KEY_STRICT_REGEX.match(default.strip().upper()):
            return default.strip().upper()
        return None

    def translate(self, natural_query: str, default_project_key: str | None = None) -> str:
        """Translate a natural language question into an optimized JQL string."""
        query = natural_query.strip()
        ticket_keys = self.extract_ticket_keys(query)
        lower_query = query.lower()

        # Pattern 1: Pending items, blockers, or dependencies for a specific ticket
        if ("pending" in lower_query or "blocker" in lower_query or "dependency" in lower_query or "depends" in lower_query) and ticket_keys:
            key = ticket_keys[0]
            return f'issue in linkedIssues("{key}") AND statusCategory != Done ORDER BY priority DESC'

        # Pattern 2: Sub-tasks or child issues of a ticket
        if ("subtask" in lower_query or "child" in lower_query or "breakdown" in lower_query) and ticket_keys:
            key = ticket_keys[0]
            return f'parent = "{key}" AND statusCategory != Done ORDER BY created ASC'

        # Pattern 3: Exact status of one or multiple tickets
        if ("status" in lower_query or "what is" in lower_query or "check" in lower_query) and ticket_keys:
            if len(ticket_keys) == 1:
                return f'key = "{ticket_keys[0]}"'
            keys_list = ", ".join([f'"{k}"' for k in ticket_keys])
            return f'key in ({keys_list})'

        # Detect project key if mentioned
        project_key = self.extract_project_key(query, default=default_project_key)

        # Pattern 4: My open tickets / assigned to me
        if "assigned to me" in lower_query or "my tickets" in lower_query or "my bugs" in lower_query:
            base_jql = "assignee = currentUser() AND statusCategory != Done"
            if project_key:
                base_jql = f'project = "{project_key}" AND {base_jql}'
            return f"{base_jql} ORDER BY updated DESC"

        # Pattern 5: High priority / Critical bugs
        if "high priority" in lower_query or "critical" in lower_query or "urgent" in lower_query:
            base_jql = 'priority in ("High", "Highest", "Critical") AND statusCategory != Done'
            if project_key:
                base_jql = f'project = "{project_key}" AND {base_jql}'
            return f"{base_jql} ORDER BY priority DESC, created DESC"

        # Pattern 6: Recently created / updated issues
        if "recent" in lower_query or "this week" in lower_query:
            base_jql = "created >= -7d OR updated >= -7d"
            if project_key:
                base_jql = f'project = "{project_key}" AND ({base_jql})'
            return f"{base_jql} ORDER BY updated DESC"

        # Pattern 7: Default fallback by ticket keys if any present
        if ticket_keys:
            keys_list = ", ".join([f'"{k}"' for k in ticket_keys])
            return f'key in ({keys_list})'

        # General project fallback
        if project_key:
            return f'project = "{project_key}" AND statusCategory != Done ORDER BY updated DESC'

        # Global open issues fallback
        return "statusCategory != Done ORDER BY updated DESC"


text_to_jql_service = TextToJQLService()
