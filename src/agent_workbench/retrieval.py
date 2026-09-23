from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Iterable


MAX_CHUNK_CHARS = 800
MAX_RESULTS = 10

_ASCII_WORD = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "which",
    "with",
}
_INSTRUCTION_PATTERNS = (
    (
        "instruction-override",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|above).{0,24}(?:instruction|rule)"
            r"|忽略.{0,12}(?:之前|以上|系统|开发者).{0,12}(?:指令|规则)",
            re.IGNORECASE,
        ),
    ),
    (
        "secret-exfiltration",
        re.compile(
            r"(?:api[ _-]?key|password|secret|token|密钥|密码).{0,28}"
            r"(?:show|print|send|upload|reveal|显示|打印|发送|上传|泄露)",
            re.IGNORECASE,
        ),
    ),
    (
        "command-execution",
        re.compile(
            r"(?:call|run|execute|invoke).{0,16}(?:shell|powershell|cmd(?:\.exe)?|bash)"
            r"|执行.{0,12}(?:命令|脚本|shell)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class DocumentChunk:
    path: str
    start_line: int
    end_line: int
    text: str


def tokenize(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    tokens = [word for word in _ASCII_WORD.findall(lowered) if word not in _STOP_WORDS]
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tuple(tokens)


def chunk_document(path: str, text: str) -> tuple[DocumentChunk, ...]:
    lines = text.splitlines()
    chunks: list[DocumentChunk] = []
    start = 0
    while start < len(lines):
        end = start
        size = 0
        while end < len(lines):
            added = len(lines[end]) + (1 if end > start else 0)
            if end > start and size + added > MAX_CHUNK_CHARS:
                break
            size += added
            end += 1
            if lines[end - 1].strip() == "" and any(
                line.strip() for line in lines[start : end - 1]
            ):
                break
        excerpt = "\n".join(lines[start:end]).strip()
        if excerpt:
            chunks.append(DocumentChunk(path, start + 1, end, excerpt))
        start = end
    return tuple(chunks)


def instruction_risks(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _INSTRUCTION_PATTERNS if pattern.search(text))


def search_documents(
    query: str,
    documents: Iterable[tuple[str, str]],
    *,
    limit: int = 5,
) -> dict[str, object]:
    if not query.strip():
        raise ValueError("Search query cannot be empty.")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"Search limit must be between 1 and {MAX_RESULTS}.")

    chunks = tuple(
        chunk
        for path, content in documents
        for chunk in chunk_document(path, content)
    )
    query_terms = Counter(tokenize(query))
    if not query_terms or not chunks:
        return {"chunksScanned": len(chunks), "matches": []}

    tokenized = [Counter(tokenize(chunk.text)) for chunk in chunks]
    document_frequency = {
        term: sum(1 for terms in tokenized if term in terms) for term in query_terms
    }
    average_length = sum(sum(terms.values()) for terms in tokenized) / len(tokenized)
    ranked: list[tuple[float, DocumentChunk, tuple[str, ...]]] = []
    for chunk, terms in zip(chunks, tokenized, strict=True):
        length = max(sum(terms.values()), 1)
        score = 0.0
        for term, query_frequency in query_terms.items():
            frequency = terms.get(term, 0)
            if frequency == 0:
                continue
            frequency_in_documents = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(chunks) - frequency_in_documents + 0.5) /
                (frequency_in_documents + 0.5)
            )
            normalized_frequency = (frequency * 2.2) / (
                frequency + 1.2 * (0.25 + 0.75 * length / max(average_length, 1))
            )
            score += inverse_frequency * normalized_frequency * query_frequency
        path_overlap = set(query_terms).intersection(tokenize(chunk.path))
        score += 0.15 * len(path_overlap)
        if score <= 0:
            continue
        ranked.append((score, chunk, instruction_risks(chunk.text)))

    ranked.sort(key=lambda item: (-item[0], item[1].path, item[1].start_line))
    matches = []
    for score, chunk, risks in ranked[:limit]:
        matches.append(
            {
                "citation": f"{chunk.path}#L{chunk.start_line}-L{chunk.end_line}",
                "path": chunk.path,
                "startLine": chunk.start_line,
                "endLine": chunk.end_line,
                "text": chunk.text,
                "score": round(score, 6),
                "instructionRisk": bool(risks),
                "riskSignals": list(risks),
            }
        )
    return {"chunksScanned": len(chunks), "matches": matches}
