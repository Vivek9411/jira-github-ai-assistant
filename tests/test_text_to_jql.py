"""Unit tests for natural language to Jira JQL query translation."""

from app.services.text_to_jql import text_to_jql_service


def test_extract_ticket_keys() -> None:
    text = "Please check ENG-104 and also take a look at PROJ-23."
    keys = text_to_jql_service.extract_ticket_keys(text)
    assert keys == ["ENG-104", "PROJ-23"]


def test_translate_pending_blockers_query() -> None:
    query = "What are the tickets pending for bug ENG-104?"
    jql = text_to_jql_service.translate(query)
    assert 'issue in linkedIssues("ENG-104")' in jql
    assert "statusCategory != Done" in jql


def test_translate_subtasks_query() -> None:
    query = "Show me the subtasks for ENG-45"
    jql = text_to_jql_service.translate(query)
    assert 'parent = "ENG-45"' in jql
    assert "statusCategory != Done" in jql


def test_translate_multiple_ticket_status() -> None:
    query = "What is the status of ENG-12 and ENG-15?"
    jql = text_to_jql_service.translate(query)
    assert 'key in ("ENG-12", "ENG-15")' in jql


def test_translate_my_assigned_tickets() -> None:
    query = "What tickets are assigned to me in project CORE?"
    jql = text_to_jql_service.translate(query)
    assert "assignee = currentUser()" in jql
    assert 'project = "CORE"' in jql


def test_translate_critical_bugs() -> None:
    query = "Show critical bugs in project ENG"
    jql = text_to_jql_service.translate(query)
    assert 'project = "ENG"' in jql
    assert "priority in" in jql
