import hashlib
import json
import math
import threading
from urllib.parse import urlparse

import httpx

from .config import Settings


class EmbeddingError(Exception):
    pass


def normalized(values, dimensions):
    if len(values) != dimensions or any(
        isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
        for x in values
    ):
        raise EmbeddingError("invalid_embedding")
    norm = math.sqrt(sum(float(x) ** 2 for x in values))
    if norm <= 1e-12:
        raise EmbeddingError("zero_embedding")
    return [float(x) / norm for x in values]


class Embedder:
    def __init__(self, settings: Settings, *, allow_download=False, transport=None):
        self.settings, self.allow_download, self.transport = settings, allow_download, transport
        self.dimensions = settings.embedding_dimensions
        if not 1 <= self.dimensions <= 16000:
            raise ValueError("Embedding dimensions out of range")
        if settings.embedding_provider == "compatible":
            if not settings.embedding_base_url.startswith("https://"):
                raise ValueError("Embedding endpoint must use HTTPS")
            if urlparse(settings.embedding_base_url).hostname == "api.deepseek.com":
                raise ValueError(
                    "Configure a separate embedding service; DeepSeek chat is not an embedding endpoint"
                )
        self.model_id = hashlib.sha256(
            json.dumps(
                {
                    "provider": settings.embedding_provider,
                    "model": settings.embedding_model,
                    "version": settings.embedding_version,
                    "dimensions": self.dimensions,
                    "endpoint": settings.embedding_base_url
                    if settings.embedding_provider == "compatible"
                    else "local",
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.lock, self.local_model = threading.Lock(), None

    def documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.embedding_provider == "local":
            with self.lock:
                if self.local_model is None:
                    from fastembed import TextEmbedding

                    self.local_model = TextEmbedding(
                        model_name=self.settings.embedding_model,
                        cache_dir=str(self.settings.embedding_cache_dir),
                        local_files_only=not self.allow_download,
                        threads=2,
                    )
                return [
                    normalized(vector.tolist(), self.dimensions)
                    for vector in self.local_model.embed(texts)
                ]
        if self.settings.embedding_provider != "compatible":
            raise EmbeddingError("embedding_disabled")
        try:
            with httpx.Client(timeout=30, transport=self.transport) as client:
                response = client.post(
                    self.settings.embedding_base_url.rstrip("/") + "/embeddings",
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.embedding_api_key.get_secret_value()
                    },
                    json={"model": self.settings.embedding_model, "input": texts},
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                if [item["index"] for item in data] != list(range(len(texts))):
                    raise EmbeddingError("embedding_count_mismatch")
                return [normalized(item["embedding"], self.dimensions) for item in data]
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise EmbeddingError("embedding_service_failed") from exc

    def query(self, text: str) -> list[float]:
        if self.settings.embedding_provider == "local":
            text = "为这个句子生成表示以用于检索相关文章：" + text
        return self.documents([text])[0]


def make_embedder(settings):
    return None if settings.embedding_provider == "none" else Embedder(settings)
