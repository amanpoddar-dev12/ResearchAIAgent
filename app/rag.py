"""Canonical session documents and bounded resolution of browser retrieval references."""

import json
import re
from copy import deepcopy
from typing import Any
from pydantic import BaseModel, Field


class ChunkReference(BaseModel):
    document_id: str = Field(max_length=200)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class RetrievedContext(BaseModel):
    session_id: str = Field(max_length=100)
    query: str = Field(max_length=4000)
    chunks: list[ChunkReference] = Field(default_factory=list, max_length=8)


class SessionIndex:
    def __init__(self, question: str = "", mode: str = "standard") -> None:
        self.state: dict[str, Any] = {"question": {"question": question}, "mode": mode}
        self.source_text: dict[str, str] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.update("research_snapshot", self.state)

    def update(self, event_type: str, data: Any) -> None:
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        if not isinstance(data, dict):
            return
        if event_type == "source_found":
            self.source_text[data["id"]] = data.get("content", "")
        if event_type == "research_snapshot":
            self.state = deepcopy(data)
            for source in data.get("sources", []):
                if source.get("content"):
                    self.source_text[source["id"]] = source["content"]
        else:
            collection = {"source_found": "sources", "claim_extracted": "findings", "finding_extracted": "findings",
                          "finding_updated": "findings", "evidence_found": "evidence", "evidence_linked": "evidence",
                          "claim_verified": "verifications", "claim_partially_verified": "verifications",
                          "claim_contradicted": "verifications", "claim_unverified": "verifications"}.get(event_type)
            if not collection:
                return
            key = "claim_id" if collection == "verifications" else "id"
            items = self.state.get(collection, [])
            self.state[collection] = [item for item in items if item.get(key) != data.get(key)] + [data]
        self.documents = self._documents()

    def _documents(self) -> dict[str, dict[str, Any]]:
        state = self.state
        sources = {item["id"]: item for item in state.get("sources", [])}
        claims = {item["id"]: item for item in state.get("findings", [])}
        documents = {}

        def add(kind: str, key: str, text: str, source_id: str | None = None,
                claim_id: str | None = None, evidence_id: str | None = None,
                evidence_ids: list[str] | None = None) -> None:
            if not text.strip():
                return
            source = sources.get(source_id, {})
            claim = claims.get(claim_id, {})
            metadata = {"type": kind, "sourceId": source_id, "url": source.get("url"),
                        "title": source.get("title", key), "claimId": claim_id, "evidenceId": evidence_id,
                        "evidenceIds": evidence_ids or [],
                        "qualityScore": source.get("quality_score_value") if source.get("quality_score_value") is not None else (source.get("quality") or {}).get("total", 0),
                        "evidenceStatus": claim.get("evidence_status", "Unverified")}
            identifier = f"{kind}:{key}"
            documents[identifier] = {"id": identifier, "text": text, "metadata": metadata}

        add("session", "scope", json.dumps({"query": state.get("question"), "mode": state.get("mode")}, ensure_ascii=False))
        for source in sources.values():
            text = "\n".join(filter(None, [self.source_text.get(source["id"], source.get("content", "")), source.get("discovery_snippet", ""), source.get("summary", "")]))
            add("source", source["id"], text, source["id"])
        for claim in claims.values():
            add("claim", claim["id"], f'{claim["claim"]}\n{claim.get("explanation", "")}\nEvidence status: {claim.get("evidence_status", "Unverified")}\nCitation validity score: {claim.get("score_citation_validity", 0)}',
                next(iter(claim.get("source_ids", [])), None), claim["id"])
        for item in state.get("evidence", []):
            add("evidence", item["id"], item["excerpt"], item["source_id"], item.get("claim_id"), item["id"])
        for item in state.get("verifications", []):
            add("validation", item["claim_id"], json.dumps(item, ensure_ascii=False), claim_id=item["claim_id"])
        for i, item in enumerate(state.get("citation_rejections", [])):
            add("rejection", str(i), json.dumps(item, ensure_ascii=False), item.get("source_id"), item.get("claim_id"), item.get("evidence_id"))
        sections = (state.get("structured_report") or {}).get("sections", [])
        if sections:
            for section in sections:
                linked = list(dict.fromkeys(eid for block in state.get("report_blocks", [])
                    if block.get("section_id") == section["id"] for eid in block.get("evidence_ids", [])))
                add("report", section["id"], section["title"] + "\n" + section.get("content", ""), evidence_ids=linked)
        else:
            for i, section in enumerate(re.split(r"(?m)(?=^#{1,3} )", state.get("final_report") or "")):
                add("report", str(i), section)
        for kind, field in [("gap", "research_gaps"), ("conflict", "conflicts")]:
            for i, item in enumerate(state.get(field, [])):
                add(kind, str(i), json.dumps(item, ensure_ascii=False))
        return documents

    def resolve(self, references: list[ChunkReference]) -> list[dict[str, Any]]:
        chunks = []
        seen = set()
        for reference in references[:8]:
            document = self.documents.get(reference.document_id)
            key = (reference.document_id, reference.start, reference.end)
            if not document or key in seen or reference.end <= reference.start or reference.end - reference.start > 1600:
                continue
            if reference.end > len(document["text"]):
                continue
            seen.add(key)
            chunks.append({**document, "text": document["text"][reference.start:reference.end]})
        return chunks
