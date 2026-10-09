"""The funder's own documents, split into citable chunks with validity dates.

Sources (scenario/call/): call text v1 (superseded) and v2 (current), and the
announcements file (one chunk per announcement). Every chunk carries
effective_from / effective_to so that "what was the rule on the deadline?" is
answered by a date filter, not by the model.

Used by: F1 citation check, the AI Search index (phase 5) and agent tools.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CALL_DIR = ROOT / "scenario" / "call"

SECTION_RE = re.compile(r"^(?:Ek-)?(\d+(?:\.\d+)+)\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    version: str
    section: str          # "4.3", "MGA-2026-ANN-2"
    title: str
    content: str
    effective_from: str
    effective_to: str | None

    def in_force(self, on: date) -> bool:
        start = date.fromisoformat(self.effective_from)
        end = date.fromisoformat(self.effective_to) if self.effective_to else None
        return start <= on and (end is None or on <= end)

    def to_dict(self) -> dict:
        return asdict(self)


def _front_matter(text: str) -> tuple[dict, str]:
    _, head, body = text.split("---", 2)
    return yaml.safe_load(head), body


def _iso(v) -> str | None:
    return v.isoformat() if isinstance(v, date) else (str(v) if v else None)


def _call_chunks(path: Path) -> list[Chunk]:
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    version = str(meta["version"])
    heading = ""
    chunks = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("## "):
            heading = line[3:]
            continue
        m = SECTION_RE.match(line.replace("**", ""))
        if not m:
            continue
        section, text = m.groups()
        prefix = "Ek-" if line.startswith("Ek-") else ""
        chunks.append(Chunk(
            id=f"{meta['doc_id']}-v{version}-{prefix}{section}".replace(".", "_"),
            doc_id=meta["doc_id"], version=version, section=f"{prefix}{section}",
            title=heading or meta["title"], content=line.replace("**", ""),
            effective_from=_iso(meta["effective_from"]), effective_to=_iso(meta.get("effective_to")),
        ))
    return chunks


def _announcement_chunks(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    meta, body = _front_matter(text)
    chunks = []
    for block in re.split(r"^## ", body, flags=re.M)[1:]:
        title, _, rest = block.partition("\n")
        _, head, content = rest.split("---", 2)
        m = yaml.safe_load(head)
        chunks.append(Chunk(
            id=m["announcement_id"].replace(".", "_"), doc_id=meta["doc_id"], version="1",
            section=m["announcement_id"], title=title.strip(), content=content.strip(),
            effective_from=_iso(m["effective_from"]), effective_to=_iso(m.get("effective_to")),
        ))
    return chunks


@lru_cache(maxsize=1)
def load_corpus() -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    for path in sorted(CALL_DIR.glob("cagri_metni_v*.md")):
        chunks += _call_chunks(path)
    chunks += _announcement_chunks(CALL_DIR / "duyurular.md")
    return tuple(chunks)


def find_section(section: str, on: date, doc_id: str = "MGA-2026-CALL") -> Chunk | None:
    """The version of a call section that was in force on a date."""
    for c in load_corpus():
        if c.doc_id == doc_id and c.section == section and c.in_force(on):
            return c
    return None


def find_announcement(name: str, on: date) -> Chunk | None:
    """'Duyuru-2' or 'MGA-2026-ANN-2' -> chunk in force on the date."""
    m = re.search(r"(\d+)\s*$", name)
    if not m:
        return None
    ann_id = f"MGA-2026-ANN-{m.group(1)}"
    return next((c for c in load_corpus() if c.section == ann_id and c.in_force(on)), None)
