from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Protocol, Sequence


@dataclass(frozen=True)
class RelevanceModelSpec:
    repository: str
    revision: str
    license: str
    file_sha256: dict[str, str]


MMARCO_MINILM_L12_SPEC = RelevanceModelSpec(
    repository="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
    revision="1427fd652930e4ba29e8149678df786c240d8825",
    license="Apache-2.0",
    file_sha256={
        "config.json": "cc2cfe51aa3fd759d21d21acf5dfd6994aa67a3c9210636d22e143699d336c77",
        "model.onnx": "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b",
        "special_tokens_map.json": "378eb3bf733eb16e65792d7e3fda5b8a4631387ca04d2015199c4d4f22ae554d",
        "tokenizer.json": "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
        "tokenizer_config.json": "e7fbfbfa6347b4e414c1cee50d142e2c2f9a895dad68b068ae83a8b564c3837e",
    },
)


MULTILINGUAL_MINILM_NLI_SPEC = RelevanceModelSpec(
    repository="MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    revision="0a71e92a985b6e1ad1828cf67ce9c459639c1dca",
    license="MIT",
    file_sha256={
        "config.json": "e08b628c4d46c8601dda34ddb40a7857e5961870b80482382d420db6dfb6e00e",
        "model.onnx": "79f8cda2b1230585a95ea0514a6f1bd21c5c986ba0529bb3261213a3e195fa6e",
        "special_tokens_map.json": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
        "tokenizer.json": "b2116c05e7305eea30394284760789681c5b3440dd4cd9a8c77539da68f9e8a6",
        "tokenizer_config.json": "10dd51e1952b6725b3c65edd16411a4ffe97a6f61636f11a7505bcb0bdb6b360",
    },
)


MDEBERTA_V3_SQUAD2_QA_SPEC = RelevanceModelSpec(
    repository="dewdev/mdeberta-v3-base-squad2-onnx",
    revision="8e70bb4dd7955b69e39e0c7347302e536a4b5f27",
    license="MIT",
    file_sha256={
        "config.json": "37a58cdb26f26ee9ec2ecd037159669c0aec28a015395c91f99736d5498174ee",
        "model.onnx": "180ed88a1c7db8bb03655d68bcaedb9e313d0e4de8b018a9d49269c9043a0363",
        "tokenizer.json": "c6b52ff7043b8e7c0712d94ffa3c8a9c9522538157a11f5b59dd9051105497b7",
        "tokenizer_config.json": "2bd085c40afa18e83c287df793b3a294ab3e6d5b27521aaed86b86658989aa5c",
    },
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class RelevanceVerifier(Protocol):
    """Scores whether each passage contains evidence for a query."""

    name: str

    def score(
        self,
        query: str,
        passages: Sequence[str],
    ) -> Sequence[float]: ...


class AnswerabilityVerifier(Protocol):
    """Scores whether each passage contains enough information to answer a query."""

    name: str

    def score(
        self,
        query: str,
        passages: Sequence[str],
    ) -> Sequence[float]: ...


_EN_COMPARISON = re.compile(
    r"\b(?:compare|differ|difference|differences|respectively|versus|vs\.?|each)\b",
    re.IGNORECASE,
)
_ZH_COMPARISON = re.compile(r"(?:比较|对比|不同|区别|差异|分别|各自)")
_CJK_TEXT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _clean_variant(value: str) -> str:
    return value.strip(" \t\r\n,;:?.，；：？！")


def _english_atomic_query(prefix: str, entity: str) -> str:
    cleaned_prefix = _clean_variant(prefix)
    cleaned_entity = _clean_variant(entity)
    compare = re.fullmatch(r"compare\s+(.+?\bfor)", cleaned_prefix, re.IGNORECASE)
    if compare is not None:
        return f"What are {compare.group(1)} {cleaned_entity}?"
    differing = re.fullmatch(
        r"how do\s+(.+?)\s+differ\s+for",
        cleaned_prefix,
        re.IGNORECASE,
    )
    if differing is not None:
        return f"What are {differing.group(1)} for {cleaned_entity}?"
    return f"{cleaned_prefix} {cleaned_entity}?"


def decompose_query(query: str) -> tuple[str, ...]:
    """Returns the original query plus conservative comparison subqueries."""

    original = query.strip()
    if not original:
        raise ValueError("Query cannot be empty.")
    variants = [original]
    english = bool(_EN_COMPARISON.search(original))
    chinese = bool(_ZH_COMPARISON.search(original))

    if english:
        for_pattern = re.search(
            r"^(?P<prefix>.+?\bfor)\s+(?P<left>[^?]+?)\s+"
            r"(?:and|versus|vs\.?)\s+(?P<right>[^?]+?)[?]?$",
            original,
            re.IGNORECASE,
        )
        direct_pattern = re.search(
            r"^(?:compare\s+)?(?P<left>[^?]+?)\s+"
            r"(?:and|versus|vs\.?)\s+(?P<right>[^?]+?)"
            r"(?:\s+(?:respectively|differ|are different).*)?[?]?$",
            original,
            re.IGNORECASE,
        )
        match = for_pattern or direct_pattern
        if match is not None:
            prefix = _clean_variant(match.groupdict().get("prefix") or "")
            left = _clean_variant(match.group("left"))
            right = _clean_variant(match.group("right"))
            if prefix:
                left = _english_atomic_query(prefix, left)
                right = _english_atomic_query(prefix, right)
            variants.extend((left, right))

    if chinese:
        separator = re.search(r"(?:与|和|以及|及)", original)
        if separator is not None:
            left = _clean_variant(original[: separator.start()])
            remainder = original[separator.end() :]
            marker = re.search(r"(?:分别|各自|在.+?(?:不同|区别|差异)|有什么不同|有何区别)", remainder)
            if marker is not None:
                right = _clean_variant(remainder[: marker.start()])
                suffix = _clean_variant(remainder[marker.end() :])
                if suffix:
                    left = f"{left} {suffix}"
                    right = f"{right} {suffix}"
                variants.extend((left, right))

    return tuple(dict.fromkeys(value for value in variants if len(value) >= 3))[:3]


class OnnxRelevanceVerifier:
    """Runs a checksum-approved multilingual cross-encoder from local files."""

    def __init__(
        self,
        session: object,
        tokenizer: object,
        spec: RelevanceModelSpec = MMARCO_MINILM_L12_SPEC,
    ) -> None:
        self._session = session
        self._tokenizer = tokenizer
        self.spec = spec
        self.name = f"onnx:{spec.repository}@{spec.revision}"

    @classmethod
    def from_local_path(cls, path: str | Path) -> OnnxRelevanceVerifier:
        model_path = Path(path).expanduser()
        if not model_path.is_dir():
            raise FileNotFoundError("Configured relevance model directory does not exist.")
        for filename, expected in MMARCO_MINILM_L12_SPEC.file_sha256.items():
            file_path = model_path / filename
            if not file_path.is_file():
                raise ValueError(
                    f"Relevance model directory does not match the approved model; missing {filename}."
                )
            if _file_sha256(file_path) != expected:
                raise ValueError(
                    f"Relevance model checksum does not match the approved model: {filename}."
                )
        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as error:
            raise RuntimeError(
                "The relevance extra is not installed; install secure-agent-workbench[relevance]."
            ) from error
        tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        session = onnxruntime.InferenceSession(
            str(model_path / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        return cls(session, tokenizer)

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        if not passages:
            return []
        try:
            import numpy
        except ImportError as error:
            raise RuntimeError("NumPy is required for relevance verification.") from error
        encodings = self._tokenizer.encode_batch(
            [(query, passage) for passage in passages]
        )
        available = {item.name for item in self._session.get_inputs()}
        inputs = {
            "input_ids": numpy.asarray(
                [encoding.ids for encoding in encodings], dtype=numpy.int64
            ),
            "attention_mask": numpy.asarray(
                [encoding.attention_mask for encoding in encodings], dtype=numpy.int64
            ),
        }
        if "token_type_ids" in available:
            inputs["token_type_ids"] = numpy.asarray(
                [encoding.type_ids for encoding in encodings], dtype=numpy.int64
            )
        logits = self._session.run(None, inputs)[0].reshape(-1)
        return [
            1.0 / (1.0 + math.exp(-max(min(float(logit), 60.0), -60.0)))
            for logit in logits
        ]


def _answerability_hypothesis(query: str) -> str:
    if _CJK_TEXT.search(query):
        return f"这段文字回答了以下问题：{query.strip()}"
    return f"This passage answers the following question: {query.strip()}"


class OnnxAnswerabilityVerifier:
    """Uses pinned multilingual NLI to reject passages neutral to the question."""

    def __init__(
        self,
        session: object,
        tokenizer: object,
        spec: RelevanceModelSpec = MULTILINGUAL_MINILM_NLI_SPEC,
    ) -> None:
        self._session = session
        self._tokenizer = tokenizer
        self.spec = spec
        self.name = f"onnx-answerability:{spec.repository}@{spec.revision}"

    @classmethod
    def from_local_path(cls, path: str | Path) -> OnnxAnswerabilityVerifier:
        model_path = Path(path).expanduser()
        if not model_path.is_dir():
            raise FileNotFoundError(
                "Configured answerability model directory does not exist."
            )
        for filename, expected in MULTILINGUAL_MINILM_NLI_SPEC.file_sha256.items():
            file_path = model_path / filename
            if not file_path.is_file():
                raise ValueError(
                    "Answerability model directory does not match the approved model; "
                    f"missing {filename}."
                )
            if _file_sha256(file_path) != expected:
                raise ValueError(
                    "Answerability model checksum does not match the approved model: "
                    f"{filename}."
                )
        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as error:
            raise RuntimeError(
                "The relevance extra is not installed; install "
                "secure-agent-workbench[relevance]."
            ) from error
        tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        session = onnxruntime.InferenceSession(
            str(model_path / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        return cls(session, tokenizer)

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        if not passages:
            return []
        try:
            import numpy
        except ImportError as error:
            raise RuntimeError("NumPy is required for answerability verification.") from error
        hypothesis = _answerability_hypothesis(query)
        encodings = self._tokenizer.encode_batch(
            [(passage, hypothesis) for passage in passages]
        )
        available = {item.name for item in self._session.get_inputs()}
        inputs = {
            "input_ids": numpy.asarray(
                [encoding.ids for encoding in encodings], dtype=numpy.int64
            ),
            "attention_mask": numpy.asarray(
                [encoding.attention_mask for encoding in encodings], dtype=numpy.int64
            ),
        }
        if "token_type_ids" in available:
            inputs["token_type_ids"] = numpy.asarray(
                [encoding.type_ids for encoding in encodings], dtype=numpy.int64
            )
        logits = self._session.run(None, inputs)[0]
        if len(logits.shape) != 2 or logits.shape[1] != 3:
            raise ValueError("Answerability model returned an unexpected output shape.")
        scores: list[float] = []
        for row in logits:
            maximum = max(float(value) for value in row)
            exponentials = [math.exp(float(value) - maximum) for value in row]
            total = sum(exponentials)
            neutral_probability = exponentials[1] / total
            scores.append(1.0 - neutral_probability)
        return scores


@dataclass(frozen=True)
class QaAnswerabilityAssessment:
    score: float
    answer: str
    start: int
    end: int


class OnnxQaAnswerabilityVerifier:
    """Scores answerability from a pinned extractive SQuAD2 ONNX model."""

    def __init__(
        self,
        session: object,
        tokenizer: object,
        spec: RelevanceModelSpec = MDEBERTA_V3_SQUAD2_QA_SPEC,
        *,
        max_answer_tokens: int = 32,
    ) -> None:
        if max_answer_tokens < 1:
            raise ValueError("max_answer_tokens must be positive.")
        self._session = session
        self._tokenizer = tokenizer
        self._max_answer_tokens = max_answer_tokens
        self.spec = spec
        self.name = f"onnx-qa-answerability:{spec.repository}@{spec.revision}"

    @classmethod
    def from_local_path(cls, path: str | Path) -> OnnxQaAnswerabilityVerifier:
        model_path = Path(path).expanduser()
        if not model_path.is_dir():
            raise FileNotFoundError(
                "Configured QA answerability model directory does not exist."
            )
        for filename, expected in MDEBERTA_V3_SQUAD2_QA_SPEC.file_sha256.items():
            file_path = model_path / filename
            if not file_path.is_file():
                raise ValueError(
                    "QA answerability model directory does not match the approved "
                    f"model; missing {filename}."
                )
            if _file_sha256(file_path) != expected:
                raise ValueError(
                    "QA answerability model checksum does not match the approved "
                    f"model: {filename}."
                )
        try:
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as error:
            raise RuntimeError(
                "The relevance extra is not installed; install "
                "secure-agent-workbench[relevance]."
            ) from error
        tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=384, strategy="only_second")
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        session = onnxruntime.InferenceSession(
            str(model_path / "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        return cls(session, tokenizer)

    def assess(
        self,
        query: str,
        passages: Sequence[str],
    ) -> Sequence[QaAnswerabilityAssessment]:
        if not passages:
            return []
        try:
            import numpy
        except ImportError as error:
            raise RuntimeError("NumPy is required for QA answerability verification.") from error
        encodings = self._tokenizer.encode_batch(
            [(query, passage) for passage in passages]
        )
        available = {item.name for item in self._session.get_inputs()}
        inputs = {
            "input_ids": numpy.asarray(
                [encoding.ids for encoding in encodings], dtype=numpy.int64
            ),
            "attention_mask": numpy.asarray(
                [encoding.attention_mask for encoding in encodings], dtype=numpy.int64
            ),
        }
        if "token_type_ids" in available:
            inputs["token_type_ids"] = numpy.asarray(
                [encoding.type_ids for encoding in encodings], dtype=numpy.int64
            )
        outputs = self._session.run(None, inputs)
        if len(outputs) != 2 or outputs[0].shape != outputs[1].shape:
            raise ValueError("QA answerability model returned unexpected outputs.")
        if outputs[0].shape[0] != len(passages):
            raise ValueError("QA answerability model returned an unexpected batch size.")

        assessments: list[QaAnswerabilityAssessment] = []
        for passage, encoding, start_logits, end_logits in zip(
            passages, encodings, outputs[0], outputs[1], strict=True
        ):
            if len(start_logits) != len(encoding.ids):
                raise ValueError(
                    "QA answerability model returned an unexpected sequence length."
                )
            null_score = float(start_logits[0]) + float(end_logits[0])
            context_indices = [
                index
                for index, sequence_id in enumerate(encoding.sequence_ids)
                if sequence_id == 1 and encoding.attention_mask[index]
            ]
            if not context_indices:
                raise ValueError("QA tokenizer produced no context tokens.")
            best_score = -math.inf
            best_start = context_indices[0]
            best_end = context_indices[0]
            context_set = set(context_indices)
            for start in context_indices:
                maximum_end = min(
                    start + self._max_answer_tokens - 1,
                    context_indices[-1],
                )
                for end in range(start, maximum_end + 1):
                    if end not in context_set:
                        break
                    score = float(start_logits[start]) + float(end_logits[end])
                    if score > best_score:
                        best_score = score
                        best_start = start
                        best_end = end
            margin = max(min(best_score - null_score, 60.0), -60.0)
            answerability_score = 1.0 / (1.0 + math.exp(-margin))
            start_character = encoding.offsets[best_start][0]
            end_character = encoding.offsets[best_end][1]
            assessments.append(
                QaAnswerabilityAssessment(
                    score=answerability_score,
                    answer=passage[start_character:end_character].strip(),
                    start=start_character,
                    end=end_character,
                )
            )
        return assessments

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        return [assessment.score for assessment in self.assess(query, passages)]
