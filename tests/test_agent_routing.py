"""Unit tests for agent intent routing and vector embeddings."""

import math
import pytest
from app.services.agent_service import agent_service
from app.services.vector_service import vector_service


def test_transition_regex_patterns() -> None:
    patterns = [
        ("mark ENG-104 as Done", "ENG-104", "Done"),
        ("close ticket PROJ-45", "PROJ-45", "Closed"),
        ("move issue CORE-89 to In Progress", "CORE-89", "In Progress"),
        ("transition ENG-12 to In Review", "ENG-12", "In Review"),
    ]
    for text, expected_key, expected_status in patterns:
        match = agent_service.TRANSITION_REGEX.search(text)
        assert match is not None, f"Failed matching '{text}'"
        key = (match.group(1) or match.group(3)).upper()
        status = (match.group(2) or "Closed").title()
        assert key == expected_key
        assert status == expected_status.title()


def test_create_issue_regex_patterns() -> None:
    text = "Create a bug in ENG: Mobile search bar overflows screen"
    match = agent_service.CREATE_ISSUE_REGEX.search(text)
    assert match is not None
    assert match.group(1).title() == "Bug"
    assert match.group(2).upper() == "ENG"
    assert "Mobile search bar overflows screen" in match.group(3)


def test_greeting_regex_patterns() -> None:
    greetings = ["hi", "hii", "hello", "hey", "good morning", "howdy"]
    for g in greetings:
        assert agent_service.GREETING_REGEX.search(g) is not None, f"Failed matching greeting: {g}"


@pytest.mark.asyncio
async def test_vector_service_embedding_dimension() -> None:
    text = "Fix authentication token timeout in Jira ticket ENG-104"
    embedding = await vector_service.generate_embedding(text)
    assert len(embedding) == 768
    magnitude = math.sqrt(sum(v * v for v in embedding))
    assert pytest.approx(magnitude, 0.01) == 1.0
