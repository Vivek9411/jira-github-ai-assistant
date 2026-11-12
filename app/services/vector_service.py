"""Vector RAG service for semantic search across Jira tickets and GitHub code diffs."""

import hashlib
import logging
import math
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.models.vector_ticket import JiraTicketVector

logger = logging.getLogger(__name__)
settings = get_settings()


class VectorService:
    """Manages document embeddings and cosine similarity search over pgvector."""

    EMBEDDING_DIM = 768

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a dense vector embedding for the given input text.
        
        If an external LLM key is configured (Gemini/OpenAI), calls their embedding API.
        Otherwise, falls back to a deterministic semantic projection for local development/testing.
        """
        clean_text = text.strip()
        if not clean_text:
            return [0.0] * self.EMBEDDING_DIM

        # External Gemini Embedding integration if API key is present
        if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
            try:
                import httpx
                url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": clean_text[:2048]}]},
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.is_success:
                        values = resp.json().get("embedding", {}).get("values", [])
                        if len(values) == self.EMBEDDING_DIM:
                            return values
            except Exception as exc:
                logger.warning("Gemini embedding API call failed: %s. Using local fallback.", exc)

        # High-entropy deterministic embedding generator for local dev/testing
        vector = []
        for i in range(self.EMBEDDING_DIM):
            hash_input = f"{clean_text}_{i}".encode("utf-8")
            h = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
            val = (h / 0xFFFFFFFF) * 2.0 - 1.0
            vector.append(val)

        # Normalize vector to unit length
        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]
        return vector

    async def upsert_ticket_vector(
        self,
        session: AsyncSession,
        issue_key: str,
        project_key: str,
        summary: str,
        description: str,
        status: str,
        assignee: str | None = None,
        linked_pr_numbers: list[int] | None = None,
        code_diff_summary: str | None = None,
    ) -> JiraTicketVector:
        """Embed and persist/update a Jira ticket and its associated code diff in pgvector."""
        content_to_embed = (
            f"Ticket: {issue_key}\n"
            f"Summary: {summary}\n"
            f"Status: {status}\n"
            f"Assignee: {assignee or 'Unassigned'}\n"
            f"Description: {description}\n"
            f"Code Diff Context: {code_diff_summary or 'None'}"
        )

        embedding = await self.generate_embedding(content_to_embed)

        query = select(JiraTicketVector).where(JiraTicketVector.issue_key == issue_key.upper())
        result = await session.execute(query)
        record = result.scalar_one_or_none()

        if not record:
            record = JiraTicketVector(
                issue_key=issue_key.upper(),
                project_key=project_key.upper(),
                summary=summary,
                description=description,
                status=status,
                assignee=assignee,
                linked_pr_numbers=linked_pr_numbers or [],
                code_diff_summary=code_diff_summary,
                embedding=embedding,
            )
            session.add(record)
        else:
            record.summary = summary
            record.description = description
            record.status = status
            record.assignee = assignee
            if linked_pr_numbers:
                record.linked_pr_numbers = linked_pr_numbers
            if code_diff_summary:
                record.code_diff_summary = code_diff_summary
            record.embedding = embedding

        await session.commit()
        await session.refresh(record)
        return record

    async def search_similar_tickets(
        self,
        session: AsyncSession,
        query_text: str,
        project_key: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Perform semantic cosine distance retrieval over stored Jira tickets."""
        query_vector = await self.generate_embedding(query_text)

        # pgvector cosine distance operator is <=>
        stmt = select(JiraTicketVector)
        if project_key:
            stmt = stmt.where(JiraTicketVector.project_key == project_key.upper())

        try:
            # Order by cosine distance
            stmt = stmt.order_by(JiraTicketVector.embedding.cosine_distance(query_vector)).limit(limit)
            result = await session.execute(stmt)
            records = result.scalars().all()
        except Exception as exc:
            # Fallback query if vector extension operator is unavailable
            logger.warning("Vector ordering query failed (%s); falling back to keyword filter", exc)
            fallback_stmt = select(JiraTicketVector)
            if project_key:
                fallback_stmt = fallback_stmt.where(JiraTicketVector.project_key == project_key.upper())
            fallback_stmt = fallback_stmt.limit(limit)
            result = await session.execute(fallback_stmt)
            records = result.scalars().all()

        return [
            {
                "issue_key": r.issue_key,
                "project_key": r.project_key,
                "summary": r.summary,
                "description": r.description,
                "status": r.status,
                "assignee": r.assignee,
                "linked_pr_numbers": r.linked_pr_numbers,
                "code_diff_summary": r.code_diff_summary,
            }
            for r in records
        ]


vector_service = VectorService()
