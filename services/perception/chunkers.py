"""Chunking strategies for different content types.

Splits raw content into semantically meaningful chunks suitable for
embedding and indexing. Each chunker preserves structural context
(headings, function boundaries, etc.) to improve retrieval quality.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from local_system.config import get_settings

settings = get_settings()


@dataclass
class Chunk:
    """A single chunk of content ready for embedding."""
    text: str
    index: int
    metadata: dict = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return len(self.text) // 4


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Split plain text by sentences, respecting chunk_size limits."""
    chunk_size = chunk_size or settings.rag.chunk_size
    chunk_overlap = chunk_overlap or settings.rag.chunk_overlap
    meta = metadata or {}

    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunks.append(Chunk(
                text=" ".join(current),
                index=len(chunks),
                metadata={**meta, "chunk_type": "text"},
            ))
            overlap_text = " ".join(current)
            overlap_start = max(0, len(overlap_text) - chunk_overlap)
            overlap = overlap_text[overlap_start:]
            current = [overlap] if overlap else []
            current_len = len(overlap)
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(Chunk(
            text=" ".join(current),
            index=len(chunks),
            metadata={**meta, "chunk_type": "text"},
        ))

    return chunks


def chunk_markdown(
    text: str,
    chunk_size: int | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Split markdown by headings, then by size within sections."""
    chunk_size = chunk_size or settings.rag.chunk_size
    meta = metadata or {}
    chunks: list[Chunk] = []

    sections = re.split(r'(?=^#{1,4}\s)', text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        heading_match = re.match(r'^(#{1,4})\s+(.+)', section)
        section_meta = {**meta, "chunk_type": "markdown"}
        if heading_match:
            section_meta["heading"] = heading_match.group(2).strip()
            section_meta["heading_level"] = len(heading_match.group(1))

        if len(section) <= chunk_size:
            chunks.append(Chunk(text=section, index=len(chunks), metadata=section_meta))
        else:
            paragraphs = section.split("\n\n")
            current_parts: list[str] = []
            current_len = 0
            for para in paragraphs:
                if current_len + len(para) > chunk_size and current_parts:
                    chunks.append(Chunk(
                        text="\n\n".join(current_parts),
                        index=len(chunks),
                        metadata=section_meta,
                    ))
                    current_parts = []
                    current_len = 0
                current_parts.append(para)
                current_len += len(para)
            if current_parts:
                chunks.append(Chunk(
                    text="\n\n".join(current_parts),
                    index=len(chunks),
                    metadata=section_meta,
                ))

    return chunks


def chunk_code(
    text: str,
    language: str = "python",
    chunk_size: int | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Split code by top-level definitions (functions, classes)."""
    chunk_size = chunk_size or settings.rag.chunk_size * 2
    meta = metadata or {}
    chunks: list[Chunk] = []

    patterns = {
        "python": r'(?=^(?:class |def |async def ))',
        "javascript": r'(?=^(?:function |class |const |export ))',
        "typescript": r'(?=^(?:function |class |const |export |interface ))',
        "rust": r'(?=^(?:fn |pub fn |struct |impl |enum |trait ))',
        "go": r'(?=^(?:func |type ))',
    }

    pattern = patterns.get(language)
    if pattern:
        blocks = re.split(pattern, text, flags=re.MULTILINE)
    else:
        blocks = re.split(r'\n{2,}', text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        block_meta = {**meta, "chunk_type": "code", "language": language}
        name_match = re.match(
            r'(?:class|def|async def|function|fn|pub fn|struct|impl|type|interface|const|export)\s+(\w+)',
            block,
        )
        if name_match:
            block_meta["symbol"] = name_match.group(1)

        if len(block) <= chunk_size:
            chunks.append(Chunk(text=block, index=len(chunks), metadata=block_meta))
        else:
            lines = block.split("\n")
            current_lines: list[str] = []
            current_len = 0
            for line in lines:
                if current_len + len(line) > chunk_size and current_lines:
                    chunks.append(Chunk(
                        text="\n".join(current_lines),
                        index=len(chunks),
                        metadata=block_meta,
                    ))
                    current_lines = []
                    current_len = 0
                current_lines.append(line)
                current_len += len(line)
            if current_lines:
                chunks.append(Chunk(
                    text="\n".join(current_lines),
                    index=len(chunks),
                    metadata=block_meta,
                ))

    return chunks


# --- Extension maps ---

_EXT_MAP = {
    ".md": "markdown", ".mdx": "markdown",
    ".txt": "text", ".log": "text", ".csv": "text",
    ".py": "code", ".js": "code", ".ts": "code", ".tsx": "code",
    ".jsx": "code", ".rs": "code", ".go": "code", ".java": "code",
    ".c": "code", ".cpp": "code", ".h": "code",
    ".yaml": "text", ".yml": "text", ".json": "text", ".toml": "text",
    ".sh": "code", ".bash": "code",
}

_LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".rs": "rust", ".go": "go",
}


def detect_content_type(filename: str) -> str:
    """Detect content type from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_MAP.get(ext, "text")


def detect_language(filename: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(filename)[1].lower()
    return _LANG_MAP.get(ext, "unknown")


def chunk_content(
    text: str,
    content_type: str = "text",
    language: str = "python",
    chunk_size: int | None = None,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Dispatch to the appropriate chunker based on content type."""
    if content_type == "code":
        return chunk_code(text, language=language, chunk_size=chunk_size, metadata=metadata)
    chunkers = {"text": chunk_text, "markdown": chunk_markdown}
    return chunkers.get(content_type, chunk_text)(text, chunk_size=chunk_size, metadata=metadata)
