from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Iterable, Sequence

from .embeddings import EmbeddingProvider
from .relevance import AnswerabilityVerifier, RelevanceVerifier, decompose_query


MAX_CHUNK_CHARS = 800
MAX_RESULTS = 10
MAX_VERIFICATION_CANDIDATES = 20
SEMANTIC_THRESHOLD = 0.24
MIN_HYBRID_SCORE = 0.0
DEFAULT_RELEVANCE_THRESHOLD = 0.5
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
    minimum_hybrid_score: float | None = None,
    relevance_verifier: RelevanceVerifier | None = None,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    decompose_verification_query: bool = False,
    atomic_relevance_threshold: float | None = None,
    require_complete_query_coverage: bool = False,
    answerability_verifier: AnswerabilityVerifier | None = None,
    answerability_threshold: float = 0.5,
    answerability_scope: str = "passage",
) -> dict[str, object]:
    if not query.strip():
        raise ValueError("Search query cannot be empty.")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"Search limit must be between 1 and {MAX_RESULTS}.")
    hybrid_score_floor = (
        MIN_HYBRID_SCORE
        if minimum_hybrid_score is None
        else minimum_hybrid_score
    )
    if not 0.0 <= hybrid_score_floor <= 1.0:
        raise ValueError("minimum_hybrid_score must be between 0 and 1.")
    if (
        not math.isfinite(relevance_threshold)
        or not 0.0 <= relevance_threshold <= 1.0
    ):
        raise ValueError("relevance_threshold must be a finite value between 0 and 1.")
    if atomic_relevance_threshold is not None and (
        not math.isfinite(atomic_relevance_threshold)
        or not 0.0 <= atomic_relevance_threshold <= 1.0
    ):
        raise ValueError(
            "atomic_relevance_threshold must be a finite value between 0 and 1."
        )
    if require_complete_query_coverage and not decompose_verification_query:
        raise ValueError(
            "require_complete_query_coverage requires decompose_verification_query."
        )
    if answerability_verifier is not None and relevance_verifier is None:
        raise ValueError("answerability_verifier requires relevance_verifier.")
    if (
        not math.isfinite(answerability_threshold)
        or not 0.0 <= answerability_threshold <= 1.0
    ):
        raise ValueError(
            "answerability_threshold must be a finite value between 0 and 1."
        )
    if answerability_scope not in {"passage", "set"}:
        raise ValueError("answerability_scope must be 'passage' or 'set'.")

    chunks = tuple(
        chunk
        for path, content in documents
        for chunk in chunk_document(path, content)
    )
    query_variants = (
        decompose_query(query)
        if relevance_verifier is not None and decompose_verification_query
        else (query,)
    )
    query_terms = Counter(tokenize(query))
    base_mode = "lexical-fallback" if embedding_fallback_reason else "lexical"
    if not chunks:
        return {
            "chunksScanned": 0,
            "retrievalMode": base_mode,
            "embeddingProvider": None,
            "fallbackReason": embedding_fallback_reason,
            "verificationMode": "disabled" if relevance_verifier is None else "verified",
            "relevanceVerifier": (
                None if relevance_verifier is None else relevance_verifier.name
            ),
            "relevanceThreshold": (
                None if relevance_verifier is None else relevance_threshold
            ),
            "verificationFailureReason": None,
            "answerabilityMode": (
                "disabled" if answerability_verifier is None else "verified"
            ),
            "answerabilityVerifier": (
                None if answerability_verifier is None else answerability_verifier.name
            ),
            "answerabilityThreshold": (
                None if answerability_verifier is None else answerability_threshold
            ),
            "answerabilityScope": (
                None if answerability_verifier is None else answerability_scope
            ),
            "answerabilitySetScores": [],
            "answerabilityCoverageComplete": (
                False if answerability_verifier is not None else None
            ),
            "queryCoverageRequired": require_complete_query_coverage,
            "queryCoverageComplete": False if relevance_verifier is not None else None,
            "coveredQueryVariants": [],
            "verificationQueryVariants": (
                list(decompose_query(query))
                if relevance_verifier is not None and decompose_verification_query
                else [query]
                if relevance_verifier is not None
                else []
            ),
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
            vectors = embedding_provider.encode(
                [*query_variants, *(chunk.text for chunk in chunks)]
            )
            if len(vectors) != len(chunks) + len(query_variants):
                raise ValueError("Embedding provider returned an unexpected vector count.")
            query_vectors = vectors[: len(query_variants)]
            semantic_scores = [
                max(
                    _cosine_similarity(query_vector, vector)
                    for query_vector in query_vectors
                )
                for vector in vectors[len(query_variants) :]
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
            if score < hybrid_score_floor:
                continue
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
    verification_mode = "disabled"
    verification_failure_reason: str | None = None
    covered_query_variants: list[str] = []
    coverage_complete: bool | None = None
    answerability_set_scores: list[dict[str, object]] = []
    answerability_coverage_complete: bool | None = None
    verified_ranked: list[
        tuple[
            tuple[float, float, float | None, DocumentChunk, tuple[str, ...]],
            float | None,
            str | None,
            float | None,
        ]
    ]
    if relevance_verifier is None:
        verified_ranked = [(item, None, None, None) for item in ranked[:limit]]
    else:
        candidates = ranked[:MAX_VERIFICATION_CANDIDATES]
        verification_passages = [
            f"{item[3].path}\n{item[3].text}" for item in candidates
        ]
        verification_mode = "verified"
        if len(query_variants) > 1:
            verification_mode = "decomposed-verified"
        try:
            score_rows: list[list[float]] = []
            answerability_rows: list[list[float]] = []
            for variant in query_variants:
                relevance_scores = list(
                    relevance_verifier.score(
                        variant,
                        verification_passages,
                    )
                )
                if len(relevance_scores) != len(candidates):
                    raise ValueError(
                        "Relevance verifier returned an unexpected score count."
                    )
                if any(
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(float(score))
                    or not 0.0 <= float(score) <= 1.0
                    for score in relevance_scores
                ):
                    raise ValueError("Relevance verifier returned an invalid score.")
                score_rows.append([float(score) for score in relevance_scores])
                if (
                    answerability_verifier is not None
                    and answerability_scope == "passage"
                ):
                    answerability_scores = list(
                        answerability_verifier.score(variant, verification_passages)
                    )
                    if len(answerability_scores) != len(candidates):
                        raise ValueError(
                            "Answerability verifier returned an unexpected score count."
                        )
                    if any(
                        isinstance(score, bool)
                        or not isinstance(score, (int, float))
                        or not math.isfinite(float(score))
                        or not 0.0 <= float(score) <= 1.0
                        for score in answerability_scores
                    ):
                        raise ValueError(
                            "Answerability verifier returned an invalid score."
                        )
                    answerability_rows.append(
                        [float(score) for score in answerability_scores]
                    )
            best_scores: list[tuple[float, str, int]] = [
                max(
                    (row[index], query_variants[row_index], row_index)
                    for row_index, row in enumerate(score_rows)
                )
                for index in range(len(candidates))
            ]
            accepted = [
                (
                    item,
                    score,
                    variant,
                    None
                    if answerability_verifier is None or answerability_scope == "set"
                    else answerability_rows[row_index][index],
                )
                for index, (item, (score, variant, row_index)) in enumerate(
                    zip(candidates, best_scores, strict=True)
                )
                if score >= relevance_threshold
                and (
                    answerability_verifier is None
                    or answerability_scope == "set"
                    or answerability_rows[row_index][index]
                    >= answerability_threshold
                )
            ]
            if len(query_variants) > 1:
                verified_ranked = []
                selected_paths: set[str] = set()
                covered_query_variants: list[str] = []
                atomic_threshold = (
                    relevance_threshold
                    if atomic_relevance_threshold is None
                    else atomic_relevance_threshold
                )
                for row_index, variant in enumerate(query_variants[1:], start=1):
                    eligible = [
                        (
                            candidates[index],
                            score_rows[row_index][index],
                            variant,
                            None
                            if answerability_verifier is None
                            or answerability_scope == "set"
                            else answerability_rows[row_index][index],
                        )
                        for index in range(len(candidates))
                        if score_rows[row_index][index] >= atomic_threshold
                        and (
                            answerability_verifier is None
                            or answerability_scope == "set"
                            or answerability_rows[row_index][index]
                            >= answerability_threshold
                        )
                        and candidates[index][3].path not in selected_paths
                    ]
                    if eligible:
                        chosen = max(
                            eligible,
                            key=lambda value: (
                                value[1],
                                value[0][0],
                                value[0][3].path,
                            ),
                        )
                        verified_ranked.append(chosen)
                        selected_paths.add(chosen[0][3].path)
                        covered_query_variants.append(variant)
                coverage_complete = len(covered_query_variants) == len(
                    query_variants[1:]
                )
                if require_complete_query_coverage and not coverage_complete:
                    verified_ranked = []
                    selected_paths.clear()
                if coverage_complete or not require_complete_query_coverage:
                    for candidate in sorted(
                        accepted,
                        key=lambda value: (
                            -value[1],
                            -value[0][0],
                            value[0][3].path,
                        ),
                    ):
                        if candidate[0][3].path in selected_paths:
                            continue
                        verified_ranked.append(candidate)
                        selected_paths.add(candidate[0][3].path)
                        if len(verified_ranked) >= limit:
                            break
                verified_ranked = verified_ranked[:limit]
            else:
                covered_query_variants = [query] if accepted else []
                coverage_complete = bool(accepted)
                verified_ranked = accepted[:limit]
            if answerability_verifier is not None and answerability_scope == "set":
                required_variants = (
                    query_variants[1:] if len(query_variants) > 1 else query_variants
                )
                if verified_ranked:
                    combined_passage = "\n\n".join(
                        f"{item[0][3].path}\n{item[0][3].text}"
                        for item in verified_ranked
                    )
                    for variant in required_variants:
                        scores = list(
                            answerability_verifier.score(variant, [combined_passage])
                        )
                        if len(scores) != 1:
                            raise ValueError(
                                "Answerability verifier returned an unexpected score count."
                            )
                        score = scores[0]
                        if (
                            isinstance(score, bool)
                            or not isinstance(score, (int, float))
                            or not math.isfinite(float(score))
                            or not 0.0 <= float(score) <= 1.0
                        ):
                            raise ValueError(
                                "Answerability verifier returned an invalid score."
                            )
                        answerability_set_scores.append(
                            {"queryVariant": variant, "score": round(float(score), 6)}
                        )
                    answerability_coverage_complete = all(
                        float(item["score"]) >= answerability_threshold
                        for item in answerability_set_scores
                    )
                    if not answerability_coverage_complete:
                        verified_ranked = []
                else:
                    answerability_coverage_complete = False
            elif answerability_verifier is not None:
                answerability_coverage_complete = bool(verified_ranked)
        except Exception as error:
            verification_mode = "failed-closed"
            failure_prefix = (
                "relevance verification failed"
                if answerability_verifier is None
                else "evidence verification failed"
            )
            verification_failure_reason = (
                f"{failure_prefix}: {type(error).__name__}"
            )
            covered_query_variants = []
            coverage_complete = False
            answerability_set_scores = []
            answerability_coverage_complete = False
            verified_ranked = []

    matches = []
    for (
        ranked_item,
        relevance_score,
        matched_query_variant,
        answerability_score,
    ) in verified_ranked:
        score, lexical_score, semantic_score, chunk, risks = ranked_item
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
                "relevanceScore": (
                    None if relevance_score is None else round(relevance_score, 6)
                ),
                "answerabilityScore": (
                    None
                    if answerability_score is None
                    else round(answerability_score, 6)
                ),
                "matchedQueryVariant": matched_query_variant,
                "instructionRisk": bool(risks),
                "riskSignals": list(risks),
            }
        )
    return {
        "chunksScanned": len(chunks),
        "retrievalMode": retrieval_mode,
        "embeddingProvider": provider_name,
        "fallbackReason": fallback_reason,
        "minimumHybridScore": hybrid_score_floor if semantic_scores is not None else None,
        "verificationMode": verification_mode,
        "relevanceVerifier": (
            None if relevance_verifier is None else relevance_verifier.name
        ),
        "relevanceThreshold": (
            None if relevance_verifier is None else relevance_threshold
        ),
        "verificationFailureReason": verification_failure_reason,
        "answerabilityMode": (
            "disabled"
            if answerability_verifier is None
            else "failed-closed"
            if verification_mode == "failed-closed"
            else "verified"
        ),
        "answerabilityVerifier": (
            None if answerability_verifier is None else answerability_verifier.name
        ),
        "answerabilityThreshold": (
            None if answerability_verifier is None else answerability_threshold
        ),
        "answerabilityScope": (
            None if answerability_verifier is None else answerability_scope
        ),
        "answerabilitySetScores": answerability_set_scores,
        "answerabilityCoverageComplete": (
            answerability_coverage_complete
            if answerability_verifier is not None
            else None
        ),
        "atomicRelevanceThreshold": (
            atomic_relevance_threshold if len(query_variants) > 1 else None
        ),
        "queryCoverageRequired": require_complete_query_coverage,
        "queryCoverageComplete": (
            coverage_complete if relevance_verifier is not None else None
        ),
        "coveredQueryVariants": covered_query_variants,
        "verificationQueryVariants": (
            list(decompose_query(query))
            if relevance_verifier is not None and decompose_verification_query
            else [query]
            if relevance_verifier is not None
            else []
        ),
        "matches": matches,
    }
