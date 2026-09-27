from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class EmbeddingModelSpec:
    repository: str
    revision: str
    license: str
    file_sha256: dict[str, str]


POTION_MODEL_SPEC = EmbeddingModelSpec(
    repository="Tokenade/potion-multilingual-128M-i8-tokenade",
    revision="ba8c55049669aa4c81211002604fac3afc3a7a89",
    license="MIT",
    file_sha256={
        "config.json": "595e4cab2093732efd5dbe084fd5c1826b5eea693b73b4c1fd971672867d2e54",
        "model.safetensors": "98587b62d9c4040e76b5c5f51d57e69c80b12b78d46fbb6b04f85ddb9b4f5890",
        "tokenizer.json": "19f1909063da3cfe3bd83a782381f040dccea475f4816de11116444a73e1b6a1",
    },
)
E5_MODEL_SPEC = EmbeddingModelSpec(
    repository="cnmoro/multilingual-e5-small-distilled-16m",
    revision="813d48d449f24bb69be047693d48eb8a680239c6",
    license="MIT",
    file_sha256={
        "config.json": "9c7891dba00700a8cec22be0ecd9d971c549bb35e57b255f3f3761c882edbd0d",
        "model.safetensors": "3a24fd8f112b71957ff37da56e1d20dc0c046c19eb610a10bf1a569522438588",
        "tokenizer.json": "cd98e5698b201ba914efb8c18b6709fa8735ab71dcad8d2b431e52e8bf68d932",
    },
)
MODEL_SPECS = (POTION_MODEL_SPEC, E5_MODEL_SPEC)
# E5 won the calibration split but did not improve held-out holistic pass rate.
# Keep the deployed default unchanged until a candidate clears a frozen gate.
DEFAULT_MODEL_SPEC = POTION_MODEL_SPEC
MODEL_REPOSITORY = DEFAULT_MODEL_SPEC.repository
MODEL_REVISION = DEFAULT_MODEL_SPEC.revision
MODEL_LICENSE = DEFAULT_MODEL_SPEC.license
MODEL_FILE_SHA256 = DEFAULT_MODEL_SPEC.file_sha256


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class EmbeddingProvider(Protocol):
    name: str

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True)
class EmbeddingConfiguration:
    provider: EmbeddingProvider | None = None
    fallback_reason: str | None = None


class Model2VecEmbeddingProvider:
    """Loads a model2vec model from an existing local directory only."""

    def __init__(self, model: object, spec: EmbeddingModelSpec = DEFAULT_MODEL_SPEC) -> None:
        self._model = model
        self.spec = spec
        self.name = f"model2vec:{spec.repository}@{spec.revision}"

    @classmethod
    def from_local_path(cls, path: str | Path) -> Model2VecEmbeddingProvider:
        model_path = Path(path).expanduser()
        if not model_path.is_dir():
            raise FileNotFoundError("Configured embedding model directory does not exist.")
        file_digests: dict[str, str] = {}
        for filename in DEFAULT_MODEL_SPEC.file_sha256:
            file_path = model_path / filename
            if not file_path.is_file():
                raise ValueError(
                    f"Embedding model directory does not match an approved model; missing {filename}."
                )
            file_digests[filename] = _file_sha256(file_path)
        spec = next(
            (
                candidate
                for candidate in MODEL_SPECS
                if candidate.file_sha256 == file_digests
            ),
            None,
        )
        if spec is None:
            raise ValueError("Embedding model checksums do not match an approved model.")
        try:
            from model2vec import StaticModel
        except ImportError as error:
            raise RuntimeError(
                "The retrieval extra is not installed; install secure-agent-workbench[retrieval]."
            ) from error
        model = StaticModel.from_pretrained(
            model_path,
            force_download=False,
            normalize=True,
        )
        return cls(model, spec)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        values = self._model.encode(
            list(texts),
            show_progress_bar=False,
            use_multiprocessing=False,
        )
        return values.tolist()


def load_embedding_configuration(path: str | None) -> EmbeddingConfiguration:
    if path is None or not path.strip():
        return EmbeddingConfiguration()
    try:
        provider = Model2VecEmbeddingProvider.from_local_path(path.strip())
    except Exception as error:
        return EmbeddingConfiguration(
            fallback_reason=f"embedding initialization failed: {type(error).__name__}"
        )
    return EmbeddingConfiguration(provider=provider)
