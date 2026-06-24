"""Семантический поиск по базе знаний на эмбеддингах OpenAI.

Векторы профилей кэшируются в knowledge_base/embeddings_cache.json и
пересчитываются только при изменении файла (по mtime+size). Для сообщества
в десятки-сотни человек перебор косинусного сходства мгновенный — отдельная
векторная БД не нужна.
"""
import json
import math
import os
from pathlib import Path

import httpx
from openai import OpenAI

KB_PATH = Path(__file__).parent.parent / "knowledge_base"
CACHE_PATH = KB_PATH / "embeddings_cache.json"
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
MAX_EMBED_CHARS = 8000  # профили короткие; режем на всякий случай


def _client() -> OpenAI:
    kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        kwargs["http_client"] = httpx.Client(proxy=proxy_url)
    return OpenAI(**kwargs)


def _embed(texts: list[str]) -> list[list[float]]:
    """Векторизует список текстов одним запросом."""
    client = _client()
    resp = client.embeddings.create(
        model=EMBED_MODEL,
        input=[t[:MAX_EMBED_CHARS] for t in texts],
    )
    return [item.embedding for item in resp.data]


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    KB_PATH.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _sig(p: Path) -> str:
    st = p.stat()
    return f"{int(st.st_mtime)}-{st.st_size}"


def _ensure_indexed(files: list[Path]) -> dict:
    """Досчитывает эмбеддинги для новых/изменённых файлов (батчем) и кэширует."""
    cache = _load_cache()
    pending = []
    for p in files:
        rel = str(p.relative_to(KB_PATH))
        if cache.get(rel, {}).get("sig") != _sig(p):
            pending.append((rel, p))
    if pending:
        texts = [p.read_text(encoding="utf-8") for _, p in pending]
        vectors = _embed(texts)
        for (rel, p), vec in zip(pending, vectors):
            cache[rel] = {"sig": _sig(p), "embedding": vec}
        _save_cache(cache)
    return cache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_search(query: str, files: list[Path], top_k: int = 5) -> list[tuple[Path, float]]:
    """Возвращает [(путь, сходство)] по убыванию смыслового сходства с запросом."""
    cache = _ensure_indexed(files)
    qvec = _embed([query])[0]
    scored = []
    for p in files:
        rel = str(p.relative_to(KB_PATH))
        entry = cache.get(rel)
        if not entry:
            continue
        scored.append((p, _cosine(qvec, entry["embedding"])))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
