from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Iterable, Sequence

from .embeddings import EmbeddingProvider


MAX_CHUNK_CHARS = 800
MAX_RESULTS = 10
SEMANTIC_THRESHOLD = 0.24
LEXICAL_WEIGHT = 0.45
SEMANTIC_WEIGHT = 0.55

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


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding vectors must have the same non-zero dimensions.")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def search_documents(
    query: str,
    documents: Iterable[tuple[str, str]],
    *,
    limit: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_fallback_reason: str | None = None,
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
    base_mode = "lexical-fallback" if embedding_fallback_reason else "lexical"
    if not chunks:
        return {
            "chunksScanned": 0,
            "retrievalMode": base_mode,
            "embeddingProvider": None,
            "fallbackReason": embedding_fallback_reason,
            "matches": [],
        }

    tokenized = [Counter(tokenize(chunk.text)) for chunk in chunks]
    document_frequency = {
        term: sum(1 for terms in tokenized if term in terms) for term in query_terms
    }
    average_length = sum(sum(terms.values()) for terms in tokenized) / len(tokenized)
    lexical_scores: list[float] = []
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
        lexical_scores.append(score)

    semantic_scores: list[float] | None = None
    provider_name: str | None = None
    fallback_reason = embedding_fallback_reason
    if embedding_provider is not None:
        try:
            vectors = embedding_provider.encode([query, *(chunk.text for chunk in chunks)])
            if len(vectors) != len(chunks) + 1:
                raise ValueError("Embedding provider returned an unexpected vector count.")
            semantic_scores = [
                _cosine_similarity(vectors[0], vector) for vector in vectors[1:]
            ]
            provider_name = embedding_provider.name
        except Exception as error:
            fallback_reason = f"embedding request failed: {type(error).__name__}"

    retrieval_mode = "hybrid" if semantic_scores is not None else (
        "lexical-fallback" if fallback_reason else "lexical"
    )
    maximum_lexical = max(lexical_scores, default=0.0)
    ranked: list[
        tuple[float, float, float | None, DocumentChunk, tuple[str, ...]]
    ] = []
    for index, (chunk, lexical_score) in enumerate(
        zip(chunks, lexical_scores, strict=True)
    ):
        normalized_lexical = (
            lexical_score / maximum_lexical if maximum_lexical > 0 else 0.0
        )
        semantic_score = None if semantic_scores is None else semantic_scores[index]
        if lexical_score <= 0 and (
            semantic_score is None or semantic_score < SEMANTIC_THRESHOLD
        ):
            continue
        score = normalized_lexical
        if semantic_score is not None:
            score = (
                LEXICAL_WEIGHT * normalized_lexical
                + SEMANTIC_WEIGHT * max(semantic_score, 0.0)
            )
        ranked.append(
            (
                score,
                lexical_score,
                semantic_score,
                chunk,
                instruction_risks(chunk.text),
            )
        )

    ranked.sort(key=lambda item: (-item[0], item[3].path, item[3].start_line))
    matches = []
    for score, lexical_score, semantic_score, chunk, risks in ranked[:limit]:
        matches.append(
            {
                "citation": f"{chunk.path}#L{chunk.start_line}-L{chunk.end_line}",
                "path": chunk.path,
                "startLine": chunk.start_line,
                "endLine": chunk.end_line,
                "text": chunk.text,
                "score": round(score, 6),
                "lexicalScore": round(lexical_score, 6),
                "semanticScore": (
                    None if semantic_score is None else round(semantic_score, 6)
                ),
                "instructionRisk": bool(risks),
                "riskSignals": list(risks),
            }
        )
    return {
        "chunksScanned": len(chunks),
        "retrievalMode": retrieval_mode,
        "embeddingProvider": provider_name,
        "fallbackReason": fallback_reason,
        "matches": matches,
    }
