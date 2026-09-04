"""Local vector-store adapter.

The build spec calls for pgvector "if available, otherwise a simple local
vector-store adapter". No pgvector extension is confirmed available here,
so similarity is computed in Python over embeddings stored as JSON columns
(fine at demo/small-corpus scale). If pgvector is later confirmed on the
Postgres instance, only this module's `top_k` function needs to change to
an SQL `ORDER BY embedding <=> query` — callers (the Knowledge/RAG Agent)
are unaffected.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from apps.api.models_db import KnowledgeChunkORM, KnowledgeDocumentORM
from packages.schemas.models import Role

# Minimum-clearance ranking for the access_role stored on each document.
# A user can read a document if their role's rank >= the document's rank.
ROLE_RANK = {Role.VIEWER: 0, Role.SUPPORT: 1, Role.MARKETING: 1, Role.ADMIN: 2}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k(db: Session, query_embedding: list[float], user_role: Role, k: int = 4) -> list[dict]:
    """Return the top-k chunks by cosine similarity, filtered by the caller's role clearance."""
    user_rank = ROLE_RANK[user_role]

    rows = (
        db.query(KnowledgeChunkORM, KnowledgeDocumentORM)
        .join(KnowledgeDocumentORM, KnowledgeChunkORM.document_id == KnowledgeDocumentORM.id)
        .all()
    )

    scored = []
    for chunk, doc in rows:
        doc_rank = ROLE_RANK.get(Role(doc.access_role), 2)
        if user_rank < doc_rank:
            continue  # filtered out by permission, per the RAG spec's "filter by permissions" step
        score = _cosine_similarity(query_embedding, chunk.embedding)
        scored.append((score, chunk, doc))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [
        {
            "score": score,
            "content": chunk.content,
            "document_id": doc.id,
            "title": doc.title,
            "source": doc.source,
            "section": chunk.section,
        }
        for score, chunk, doc in scored[:k]
    ]
