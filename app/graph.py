"""A projection of the existing state, never a second stored research model."""


def derive_graph(state):
    nodes = [{"id": "question", "type": "question", "label": state.question.question}]
    edges = []
    for claim in state.findings:
        nodes.append({"id": claim.id, "type": "claim", "label": claim.claim, "status": claim.evidence_status})
        edges.append({"source": "question", "target": claim.id, "type": "investigates"})
        edges.extend({"source": claim.id, "target": other, "type": "depends_on"} for other in claim.depends_on)
        edges.extend({"source": claim.id, "target": item, "type": "evidence"} for item in claim.evidence_ids)
    for item in state.evidence:
        nodes.append({"id": item.id, "type": "evidence", "label": item.excerpt, "status": item.relation})
        edges.append({"source": item.id, "target": item.source_id, "type": "retrieved_from"})
    for source in state.sources:
        nodes.append({"id": source.id, "type": "source", "label": source.title})
    for index, conflict in enumerate(state.conflicts, 1):
        identifier = f"X{index}"
        nodes.append({"id": identifier, "type": "conflict", "label": conflict.topic})
        edges.extend({"source": source, "target": identifier, "type": "conflicts"} for source in dict.fromkeys(conflict.source_a + conflict.source_b))
        edges.extend({"source": claim, "target": identifier, "type": "contradiction"} for claim in conflict.claim_ids)
    known = {node["id"] for node in nodes}
    return {"nodes": nodes, "edges": [edge for edge in edges if edge["source"] in known and edge["target"] in known]}
