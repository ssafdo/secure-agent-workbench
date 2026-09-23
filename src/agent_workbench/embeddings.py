from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol, Sequence


MODEL_REPOSITORY = "Tokenade/potion-multilingual-128M-i8-tokenade"
MODEL_REVISION = "ba8c55049669aa4c81211002604fac3afc3a7a89"
MODEL_LICENSE = "MIT"
MODEL_FILE_SHA256 = {
    "config.json": "595e4cab2093732efd5dbe084fd5c1826b5eea693b73b4c1fd971672867d2e54",
    "model.safetensors": "98587b62d9c4040e76b5c5f51d57e69c80b12b78d46fbb6b04f85ddb9b4f5890",
    "tokenizer.json": "19f1909063da3cfe3bd83a782381f040dccea475f4816de11116444a73e1b6a1",
}


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

    name = f"model2vec:{MODEL_REPOSITORY}@{MODEL_REVISION}"

    def __init__(self, model: object) -> None:
        self._model = model

    @classmethod
    def from_local_path(cls, path: str | Path) -> Model2VecEmbeddingProvider:
        model_path = Path(path).expanduser()
        if not model_path.is_dir():
            raise FileNotFoundError("Configured embedding model directory does not exist.")
        for filename, expected in MODEL_FILE_SHA256.items():
            file_path = model_path / filename
            if not file_path.is_file():
                raise FileNotFoundError(f"Embedding model is missing {filename}.")
            digest = _file_sha256(file_path)
            if digest != expected:
                raise ValueError(f"Embedding model checksum mismatch for {filename}.")
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
        return cls(model)

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
