"""Single place that builds authenticated Azure clients (Entra ID only, no keys).

Two OpenAI-compatible endpoints exist on a Foundry resource:
  * project endpoint  https://<acct>.services.ai.azure.com/api/projects/<proj>
      -> AIProjectClient.get_openai_client(): Responses API, agents, tracing.
  * account endpoint  https://<acct>.services.ai.azure.com/openai/v1
      -> plain OpenAI client: embeddings (the project route returned 404 for
         embeddings on 2026-10-01, see docs/lessons/00-ortam.md).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
PROMPT_SHIELDS_API_VERSION = "2024-09-01"


@lru_cache(maxsize=1)
def credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()


def project_endpoint() -> str:
    return os.environ["FOUNDRY_PROJECT_ENDPOINT"]


def account_endpoint() -> str:
    return project_endpoint().split("/api/projects")[0]


@lru_cache(maxsize=1)
def project_client():
    from azure.ai.projects import AIProjectClient

    return AIProjectClient(endpoint=project_endpoint(), credential=credential())


def chat_client() -> OpenAI:
    """OpenAI client scoped to the Foundry project (Responses API)."""
    return project_client().get_openai_client()


@lru_cache(maxsize=1)
def embedding_client() -> OpenAI:
    """OpenAI client on the account endpoint; token refreshed per request."""
    token_provider = get_bearer_token_provider(credential(), COGNITIVE_SCOPE)
    return OpenAI(base_url=f"{account_endpoint()}/openai/v1", api_key=token_provider)


def chat_deployment() -> str:
    return os.environ["CHAT_DEPLOYMENT"]


def embedding_deployment() -> str:
    return os.environ["EMBEDDING_DEPLOYMENT"]


PROMPT_SHIELDS_MAX_DOCS = 5  # service limit per request (400 InvalidRequestBody above this)


def shield_documents(documents: list[str], user_prompt: str = "") -> list[bool]:
    """Prompt Shields document-attack check. Returns one flag per document.

    Send paragraph-sized chunks, not whole documents. Measured on 2026-10-01
    (deterministic over 3 runs):
      * English injection: detected alone and inside context.
      * Turkish injection: detected alone and inside 3 sentences of context,
        MISSED inside 1 sentence of context and inside the full proposal.
    Paragraph-level chunking plus the local hidden-text detector covers this gap.
    """
    token = credential().get_token(COGNITIVE_SCOPE).token
    url = os.environ["CONTENT_SAFETY_ENDPOINT"].rstrip("/") + "/contentsafety/text:shieldPrompt"
    flags: list[bool] = []
    for start in range(0, len(documents), PROMPT_SHIELDS_MAX_DOCS):
        batch = documents[start:start + PROMPT_SHIELDS_MAX_DOCS]
        resp = requests.post(
            url,
            params={"api-version": PROMPT_SHIELDS_API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
            json={"userPrompt": user_prompt, "documents": batch},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"Prompt Shields {resp.status_code}: {resp.text[:300]}")
        flags += [d["attackDetected"] for d in resp.json()["documentsAnalysis"]]
    return flags
