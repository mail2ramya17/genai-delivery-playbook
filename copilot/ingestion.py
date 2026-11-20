"""Ingestion: load source documents, clean and chunk them, and KEEP their access labels.

Pin 2 of the playbook: documents keep their access labels through ingestion, so
retrieval can only ever return what the calling user is allowed to see.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    groups: frozenset[str]
    classification: str = "internal"
    metadata: dict = field(default_factory=dict, compare=False, hash=False)


def parse_document(raw: str, source: str = "<memory>") -> tuple[dict, str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        raise ValueError(f"{source}: missing front matter with id/groups (fail closed)")
    meta = yaml.safe_load(match.group(1)) or {}
    for key in ("id", "groups"):
        if not meta.get(key):
            raise ValueError(f"{source}: front matter must define '{key}' (fail closed)")
    return meta, match.group(2)


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)          # strip stray HTML
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_document(meta: dict, body: str, max_sentences: int = 2) -> list[Chunk]:
    sentences = split_sentences(clean(body))
    chunks = []
    for i in range(0, len(sentences), max_sentences):
        chunks.append(
            Chunk(
                chunk_id=f"{meta['id']}#{i // max_sentences}",
                doc_id=str(meta["id"]),
                title=str(meta.get("title", meta["id"])),
                text=" ".join(sentences[i : i + max_sentences]),
                groups=frozenset(meta["groups"]),
                classification=str(meta.get("classification", "internal")),
            )
        )
    return chunks


def load_directory(path: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for file in sorted(Path(path).glob("*.md")):
        meta, body = parse_document(file.read_text(encoding="utf-8"), str(file))
        chunks.extend(chunk_document(meta, body))
    return chunks
