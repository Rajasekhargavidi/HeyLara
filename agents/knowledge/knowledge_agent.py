"""Knowledge / RAG Agent — Phase 5.

Ingests PDF/DOCX/TXT/Markdown into chunked, embedded, permission-tagged
storage, and answers questions grounded only in retrieved chunks. Follows
the RAG spec exactly: retrieve -> filter by permission -> cite source
metadata -> answer only from supported information -> say "I don't have
confirmed information" when evidence is missing.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.models_db import KnowledgeChunkORM, KnowledgeDocumentORM
from packages.config.llm_provider import LLMProvider
from packages.schemas.models import Role
from tools.knowledge.vector_store import ROLE_RANK, top_k
from tools.registry.registry import registry
from tools.research.chunker import chunk_text
from tools.research.extractors import extract_text

AGENT_NAME = "knowledge_agent"

NO_EVIDENCE_ANSWER = "I don't have confirmed information about that in the company knowledge base."

ANSWER_SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered context passages provided below. "
    "Every factual claim must be attributable to one of the passages — cite it inline "
    "as [n] matching the passage number. Do not use outside knowledge. Do not invent "
    "company facts, pricing, metrics, or policies. If the passages don't contain the "
    "answer, reply exactly: \"" + NO_EVIDENCE_ANSWER + "\""
)


def ingest_document(
    db: Session,
    actor_id: str,
    title: str,
    source: str,
    file_path: str | None = None,
    raw_bytes: bytes | None = None,
    raw_text: str | None = None,
    access_role: Role = Role.VIEWER,
    llm: LLMProvider | None = None,
) -> KnowledgeDocumentORM:
    registry.call("ingest_document", actor=actor_id, title=title, source=source)

    if raw_text is None:
        if file_path is None:
            raise ValueError("Either file_path or raw_text must be provided")
        raw_text = extract_text(file_path, raw_bytes=raw_bytes)

    chunks = chunk_text(raw_text)
    if not chunks:
        raise ValueError("No extractable text found in document")

    document = KnowledgeDocumentORM(
        title=title,
        source=source,
        access_role=access_role.value,
        created_by=actor_id,
    )
    db.add(document)
    db.flush()  # assign document.id before creating chunks

    for i, chunk in enumerate(chunks):
        embedding = llm.embed(chunk) if llm else []
        db.add(KnowledgeChunkORM(
            document_id=document.id,
            section=f"chunk {i + 1}",
            content=chunk,
            embedding=embedding,
        ))

    db.commit()
    db.refresh(document)
    document.chunk_count = len(chunks)  # not persisted, convenience for the caller
    return document


def list_documents(db: Session, user_role: Role) -> list[KnowledgeDocumentORM]:
    user_rank = ROLE_RANK[user_role]
    docs = db.query(KnowledgeDocumentORM).order_by(KnowledgeDocumentORM.created_at.desc()).all()
    return [d for d in docs if user_rank >= ROLE_RANK.get(Role(d.access_role), 2)]


def answer_from_knowledge(db: Session, llm: LLMProvider, user_role: Role, question: str, k: int = 4) -> dict:
    registry.call("search_knowledge", actor=AGENT_NAME, query=question)
    query_embedding = llm.embed(question)
    chunks = top_k(db, query_embedding, user_role, k=k)

    if not chunks:
        return {"answer": NO_EVIDENCE_ANSWER, "sources": []}

    context = "\n\n".join(
        f"[{i + 1}] (source: {c['title']}, {c['section']})\n{c['content']}"
        for i, c in enumerate(chunks)
    )
    prompt = f"Context passages:\n\n{context}\n\nQuestion: {question}"
    answer = llm.generate(prompt, system=ANSWER_SYSTEM_PROMPT).strip()

    return {
        "answer": answer,
        "sources": [
            {
                "n": i + 1,
                "title": c["title"],
                "document_id": c["document_id"],
                "section": c["section"],
                "relevance_score": round(c["score"], 3),
            }
            for i, c in enumerate(chunks)
        ],
    }
