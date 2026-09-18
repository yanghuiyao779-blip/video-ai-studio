"""Batched, validated embeddings shared by creator and conversation retrieval."""
import math
import httpx
from app.core.config import get_settings


def embed_texts(config, inputs: list[str], dimensions: int = 1536) -> list[list[float]]:
    if not config or not config.embedding_model:
        raise RuntimeError("未配置 Embedding 模型")
    output = []
    with httpx.Client(timeout=get_settings().llm_timeout_seconds) as client:
        for offset in range(0, len(inputs), 32):
            batch = inputs[offset:offset + 32]
            response = client.post(f"{config.base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={"model": config.embedding_model, "input": batch})
            response.raise_for_status()
            data = response.json().get("data") or []
            if len(data) != len(batch):
                raise RuntimeError("Embedding response count mismatch")
            # Providers are allowed to return rows out of order.
            if all(isinstance(item.get("index"), int) for item in data):
                data = sorted(data, key=lambda item: item["index"])
                if [item["index"] for item in data] != list(range(len(batch))):
                    raise RuntimeError("Embedding response index mismatch")
            for item in data:
                vector = item.get("embedding")
                if not isinstance(vector, list) or len(vector) != dimensions:
                    raise RuntimeError(f"Embedding dimensions must be {dimensions}")
                if any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in vector):
                    raise RuntimeError("Embedding contains non-finite values")
                output.append([float(v) for v in vector])
    return output
