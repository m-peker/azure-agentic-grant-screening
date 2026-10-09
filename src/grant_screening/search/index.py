"""Phase 5: hybrid search over the funder's documents (Azure AI Search, Free tier).

  BM25 (keywords)  finds exact tokens: "Duyuru-2", "4.3", "ON-2025-031"
  vector (meaning) finds paraphrases: "anonim hasta verisi için onay gerekir mi?"
  RRF              fuses both rankings; the semantic ranker re-orders the top results
  filter           effective_from <= date <= effective_to keeps superseded text out

Embeddings are computed client-side (Free tier cannot call Azure OpenAI with a
managed identity, so integrated vectorization is not used) and cached locally.
"""
from __future__ import annotations

import os
from datetime import date

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from grant_screening import azure_clients as az
from grant_screening.cache import cached_json, digest
from grant_screening.corpus import Chunk, load_corpus

INDEX_NAME = "call-docs"
VECTOR_DIM = 1536
SEMANTIC_CONFIG = "call-semantic"


def _endpoint() -> str:
    return os.environ["SEARCH_ENDPOINT"]


def embed(texts: list[str]) -> list[list[float]]:
    model = az.embedding_deployment()

    def call(t: str) -> list[float]:
        return az.embedding_client().embeddings.create(model=model, input=t).data[0].embedding

    return [cached_json("embeddings", digest(model, t), lambda t=t: call(t)) for t in texts]


def index_definition() -> SearchIndex:
    return SearchIndex(
        name=INDEX_NAME,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="version", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="section", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="tr.microsoft"),
            SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="tr.microsoft"),
            SimpleField(name="effective_from", type=SearchFieldDataType.DateTimeOffset, filterable=True),
            SimpleField(name="effective_to", type=SearchFieldDataType.DateTimeOffset, filterable=True),
            SearchField(name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                        searchable=True, vector_search_dimensions=VECTOR_DIM,
                        vector_search_profile_name="hnsw-profile"),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        ),
        semantic_search=SemanticSearch(configurations=[SemanticConfiguration(
            name=SEMANTIC_CONFIG,
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="title"),
                content_fields=[SemanticField(field_name="content")],
            ),
        )]),
    )


def _to_doc(c: Chunk, vector: list[float]) -> dict:
    def ts(d: str | None) -> str | None:
        return f"{d}T00:00:00Z" if d else None

    return {"id": c.id, "doc_id": c.doc_id, "version": c.version, "section": c.section, "title": c.title,
            "content": c.content, "effective_from": ts(c.effective_from), "effective_to": ts(c.effective_to),
            "content_vector": vector}


def build_index() -> int:
    SearchIndexClient(_endpoint(), az.credential()).create_or_update_index(index_definition())
    chunks = list(load_corpus())
    vectors = embed([f"{c.title}\n{c.content}" for c in chunks])
    client = SearchClient(_endpoint(), INDEX_NAME, az.credential())
    results = client.upload_documents([_to_doc(c, v) for c, v in zip(chunks, vectors)])
    return sum(1 for r in results if r.succeeded)


def in_force_filter(on: date) -> str:
    d = f"{on.isoformat()}T00:00:00Z"
    return f"effective_from le {d} and (effective_to eq null or effective_to ge {d})"


def search_call_docs(query: str, on: date | None, top: int = 3, semantic: bool = True) -> list[dict]:
    """Hybrid search. on=None disables the validity filter (used only to show the trap)."""
    vector = embed([query])[0]
    client = SearchClient(_endpoint(), INDEX_NAME, az.credential())
    kwargs = dict(
        search_text=query,
        vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=10, fields="content_vector")],
        filter=in_force_filter(on) if on else None,
        select=["id", "doc_id", "version", "section", "title", "content", "effective_from", "effective_to"],
        top=top,
    )
    if semantic:
        kwargs.update(query_type="semantic", semantic_configuration_name=SEMANTIC_CONFIG)
    hits = []
    for r in client.search(**kwargs):
        hits.append({k: r.get(k) for k in ("id", "section", "version", "title", "content")}
                    | {"score": r.get("@search.score"), "reranker_score": r.get("@search.reranker_score")})
    return hits
