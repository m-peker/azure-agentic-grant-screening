# Agentic Grant Screening on Azure

A complete, hands-on learning project for building **agentic AI systems on Microsoft Azure**. A fictional research foundation screens grant proposals for eligibility before they reach the scientific panel.

> Numbers come from code, interpretation from the model, exploration from agents, decisions from humans.

The pipeline has a deterministic backbone, implemented as a **Microsoft Agent Framework workflow** with checkpointing and human-in-the-loop. LLMs locate and quote information. Code verifies every quote and does all arithmetic. Two budgeted, read-only **agents** run only for what the rulebook does not cover. A **program officer** makes the final decision in a web app protected by Entra ID.

![Panel](docs/img/panel.png)

![Detail: plain-language assessment, findings, checks and the officer's decision](docs/img/detay.png)

## Results

Measured over 3 trials × 4 proposals against a golden set (`docs/eval_report_v3.md`):

| Metric | Result |
|---|---|
| Final decision correct | 12/12 |
| Deficiency templates exact | 12/12 |
| Rule results correct | 93/93 |
| PII leaks to the model | 0 |
| Prompt-injection variants caught (red team) | 7/7 |
| Cost per proposal | ≈ $0.008 (early exit $0.0017) |
| Fixed monthly cost of the whole environment | ≈ $0 |

## What it demonstrates

- **Numbers never come from the LLM.** Budget figures are read from Document Intelligence table cells. Dates, durations and counts are parsed by code from verified quotes.
- **Early-exit gate, blind screening, versioned sources** with date-filtered hybrid search.
- **Three-layer injection defence:** invisible-text detection, Prompt Shields per paragraph, and PDF metadata checks. The decision stays in code even when all detectors are bypassed.
- **Budgeted, read-only agents** whose evidence is verified by code, plus an LLM judge with one critic-driven revision round. Hosted on Foundry Agent Service as a demo.
- **Evaluation that found real bugs:** multi-trial runs exposed a wrongful rejection and a missed risk. Both are fixed and covered by tests.
- **Feedback loop:** officer-approved agent findings became rules in rulebook v3. Agent runs dropped from 6 to 0 with the same accuracy and about 25% lower cost.

## Azure services

Microsoft Foundry · Azure OpenAI (gpt-5.4-mini, text-embedding-3-small) · Foundry Agent Service · Microsoft Agent Framework · Azure AI Search (Free) · Document Intelligence (F0) · AI Content Safety Prompt Shields (F0) · Azure AI Language (F0) · Application Insights · Cosmos DB (serverless) · Key Vault · App Service (F1) with Easy Auth · Managed Identity · Bicep.

## Quick start

Once the environment exists, one command opens the UI. Upload a proposal PDF (samples in `scenario/upload_samples/`), follow the review live, and decide:

```bash
python scripts/ui.py          # http://127.0.0.1:8000
```

First-time setup:

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
pytest                                   # 95 offline tests, no Azure needed

az login
az group create -n rg-grant-screening-dev -l swedencentral
export DEVELOPER_PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
az deployment group create -g rg-grant-screening-dev -n main -f infra/main.bicep -p infra/main.bicepparam
python scripts/write_env.py && python scripts/smoke_test.py
python scripts/build_pdfs.py && python scripts/build_search_index.py
python scripts/ui.py
```

Full guide in Turkish: **[docs/REHBER.md](docs/REHBER.md)**.

## Repository layout

| Path | Contents |
|---|---|
| `docs/REHBER.md` | The guide: concepts, architecture, every Azure service, measurements, costs, setup |
| `docs/lessons/` | One lesson note per phase (00–10) |
| `docs/architecture.md` | Architecture, a step-by-step walkthrough of one proposal, and every tool and technique used |
| `docs/eval_report_v2.md`, `docs/eval_report_v3.md` | Generated evaluation reports |
| `infra/` | Bicep for all Azure resources |
| `src/grant_screening/` | Pipeline: intake, structure, rules, llm_stages, agents, search, workflow |
| `webapp/` | Program officer UI (FastAPI + Jinja2). Local mode runs screenings live; cloud mode on App Service with Entra sign-in |
| `scripts/` | Entry points: screening, workflow, red team, deployment, feedback |
| `eval/` | Golden-set evaluation and Foundry evaluators |
| `scenario/` | Fully synthetic call documents, rulebooks v2/v3, registry, templates, four proposals, golden results |
| `tests/` | Offline tests with recorded service outputs |

## Disclaimer

All organisations, people, identifiers and documents in this repository are fictional. Identification and phone numbers are deliberately in invalid formats. Prices and service limits were verified in October 2026 and change over time.
