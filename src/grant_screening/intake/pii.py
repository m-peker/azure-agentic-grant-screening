"""Stage A3: blind screening — replace applicant identity with pseudonyms.

Two detectors are combined because neither is enough alone (measured 2026-10-01):
  * Azure AI Language PII found person names and e-mails in Turkish text,
    but missed the phone number and the national ID number.
  * Regular expressions catch fixed formats (T.C. kimlik, ORCID, phone, e-mail)
    but cannot recognise names.

The mapping pseudonym -> real value never leaves this process: it is stored
next to the intake result under .cache/ and is used only by code (for example
the pre-approval registry lookup by ORCID in stage D1). The LLM sees pseudonyms.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from grant_screening import azure_clients as az
from grant_screening.cache import cached_json, digest

# PhoneNumber is deliberately NOT requested from Language: on Turkish text it
# tagged the application number "2026-0147" and fragments of the ORCID as phones.
# Phones are caught by the regex below instead.
LANGUAGE_CATEGORIES = ["Person", "Email"]
LANGUAGE_MIN_CONFIDENCE = 0.6
LANGUAGE_MAX_CHARS = 5000  # synchronous PII API accepts up to 5,120 characters per document
LANGUAGE_MAX_DOCS = 5

REGEX_DETECTORS: list[tuple[str, re.Pattern]] = [
    ("ORCID", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")),
    ("KIMLIK", re.compile(r"\b\d{11}\b")),
    ("EPOSTA", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("TELEFON", re.compile(r"(?:\+90|0)\s*\(?\d{3}\)?\s*\d{3}\s*\d{2}\s*\d{2}\b")),
]
LANGUAGE_TO_LABEL = {"Person": "KISI", "Email": "EPOSTA"}

# Business identifiers that later stages need verbatim. Never pseudonymise them,
# and never accept an entity that is a fragment of one.
PROTECTED_PATTERNS = [
    re.compile(r"\bMGA-\d{4}(?:-\d{4})?\b"),   # call / application ids
    re.compile(r"\bON-\d{4}-\d{3}\b"),          # pre-approval ids
]

# Lines in the applicant block whose value is identity even if no detector fires.
LABELLED_FIELDS = {"Kurum": "KURUM"}


@dataclass
class Pseudonymizer:
    mapping: dict[str, str] = field(default_factory=dict)   # pseudonym -> real value
    _reverse: dict[str, str] = field(default_factory=dict)  # real value -> pseudonym
    _counters: dict[str, int] = field(default_factory=dict)

    def token_for(self, label: str, value: str) -> str:
        value = value.strip()
        if value in self._reverse:
            return self._reverse[value]
        n = self._counters.get(label, 0) + 1
        self._counters[label] = n
        token = f"[{label}_{n}]"
        self.mapping[token] = value
        self._reverse[value] = token
        return token

    def apply(self, text: str) -> str:
        # Longest values first so "Dr. Elif Arslan" wins over "Elif Arslan".
        for value in sorted(self._reverse, key=len, reverse=True):
            text = text.replace(value, self._reverse[value])
        return text

    def counts(self) -> dict[str, int]:
        return dict(self._counters)


def regex_entities(text: str) -> list[tuple[str, str]]:
    found = []
    for label, pattern in REGEX_DETECTORS:
        found += [(label, m.group(0)) for m in pattern.finditer(text)]
    return found


def labelled_field_entities(text: str) -> list[tuple[str, str]]:
    found = []
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in LABELLED_FIELDS and value.strip():
            found.append((LABELLED_FIELDS[key.strip()], value.strip()))
    return found


def _chunks(texts: list[str]) -> list[str]:
    """Pack paragraphs into documents under the Language size limit."""
    docs, current = [], ""
    for t in texts:
        if len(current) + len(t) + 1 > LANGUAGE_MAX_CHARS and current:
            docs.append(current)
            current = ""
        current = f"{current}\n{t}" if current else t
    if current:
        docs.append(current)
    return docs


def language_entities(texts: list[str]) -> list[tuple[str, str]]:
    docs = _chunks(texts)

    def call() -> list[list[str]]:
        from azure.ai.textanalytics import TextAnalyticsClient

        client = TextAnalyticsClient(os.environ["LANGUAGE_ENDPOINT"], az.credential())
        out = []
        for i in range(0, len(docs), LANGUAGE_MAX_DOCS):
            for res in client.recognize_pii_entities(docs[i:i + LANGUAGE_MAX_DOCS], language="tr",
                                                     categories_filter=LANGUAGE_CATEGORIES):
                if res.is_error:
                    raise RuntimeError(f"Language PII error: {res.error}")
                out += [[e.category, e.text] for e in res.entities
                        if e.confidence_score >= LANGUAGE_MIN_CONFIDENCE]
        return out

    key = digest("pii-v1", ",".join(LANGUAGE_CATEGORIES), *docs)
    return [(LANGUAGE_TO_LABEL[c], t) for c, t in cached_json("pii", key, call)]


def _is_protected(value: str, protected: set[str], accepted: list[str]) -> bool:
    """True if value is, or is a fragment of, a protected id or an already accepted entity."""
    v = value.strip()
    return any(v in p for p in protected) or any(v != a and v in a for a in accepted)


def build_pseudonymizer(applicant_block: str, all_texts: list[str], use_language: bool = True) -> Pseudonymizer:
    """Detect identity in the applicant block and everywhere else; return the mapper.

    Order matters: labelled fields and regex (precise) are accepted first; Language
    entities (fuzzy) are accepted only if they are not fragments of those.
    """
    joined = "\n".join(all_texts)
    protected = {m.group(0) for p in PROTECTED_PATTERNS for m in p.finditer(joined)}
    ps = Pseudonymizer()
    accepted: list[str] = []

    precise = labelled_field_entities(applicant_block) + regex_entities(joined)
    fuzzy = language_entities(all_texts) if use_language else []
    for label, value in precise + fuzzy:
        if _is_protected(value, protected, accepted):
            continue
        ps.token_for(label, value)
        accepted.append(value.strip())
    return ps
