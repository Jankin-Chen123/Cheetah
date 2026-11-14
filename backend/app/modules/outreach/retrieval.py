"""Hybrid lexical/semantic ranking after eligibility filtering; cache stores no raw text."""

import hashlib
import json
import math
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor

from app.integrations.bailian import ModelUnavailable
from app.integrations.embeddings import embed_text


def terms(text):
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    return set(w for w in words if len(w) > 1) | {
        word[i : i + 2] for word in words for i in range(len(word) - 1)
    }


def method_text(item):
    content = item["content"]
    fields = (
        "topic",
        "trigger_conditions",
        "question_examples",
        "followup_strategy",
        "source_text",
        "source_context",
        "exceptions",
    )
    return "\n".join(str(content.get(k, "")) for k in fields)[:5000]


def cached_vector(settings, text):
    identity = settings.ark_base_url + settings.ark_embedding_model + settings.ark_embedding_api
    digest = hashlib.sha256((identity + "\0" + text).encode()).hexdigest()
    root = settings.retrieval_cache_dir
    root.mkdir(parents=True, exist_ok=True)
    path = root / (digest + ".json")
    try:
        vector = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(vector, list)
            and 2 <= len(vector) <= 8192
            and all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector)
        ):
            return vector
    except (OSError, ValueError):
        pass
    vector = embed_text(settings, text)
    handle, name = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(vector, file)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return vector


def hybrid_rank(settings, query, candidates, limit=3):
    if not candidates or not query.strip():
        return [], {"mode": "none", "candidate_count": len(candidates)}
    texts = [method_text(item) for item in candidates]
    query_terms = terms(query)
    lexical = []
    for text in texts:
        tokens = terms(text)
        lexical.append(len(query_terms & tokens) / max(len(query_terms), 1))
    error = None
    try:
        qv = embed_text(settings, query[:2000])
        with ThreadPoolExecutor(max_workers=4) as pool:
            vectors = list(pool.map(lambda t: cached_vector(settings, t), texts))
        semantic = []
        for vector in vectors:
            if len(vector) != len(qv):
                raise ModelUnavailable("EMBEDDING_DIMENSION_MISMATCH")
            semantic.append(sum(a * b for a, b in zip(qv, vector, strict=True)))
        mode = "hybrid"
    except (ModelUnavailable, OSError) as failure:
        semantic = [0.0] * len(candidates)
        mode = "lexical_degraded"
        error = (
            str(failure) if isinstance(failure, ModelUnavailable) else "EMBEDDING_CACHE_UNAVAILABLE"
        )
    lex_order = sorted(
        range(len(candidates)), key=lambda i: (-lexical[i], candidates[i]["entry_id"])
    )
    sem_order = sorted(
        range(len(candidates)), key=lambda i: (-semantic[i], candidates[i]["entry_id"])
    )
    scores = {}
    for order in (lex_order, sem_order) if mode == "hybrid" else (lex_order,):
        for rank, index in enumerate(order, 1):
            scores[index] = scores.get(index, 0) + 1 / (60 + rank)
    ranked = sorted(scores, key=lambda i: (-scores[i], candidates[i]["entry_id"]))
    selected = []
    for index in ranked:
        if lexical[index] < 0.12 and (
            mode != "hybrid" or semantic[index] < settings.retrieval_min_similarity
        ):
            continue
        selected.append(
            {
                **candidates[index],
                "retrieval": {
                    "mode": mode,
                    "lexical_score": round(lexical[index], 4),
                    "semantic_score": round(semantic[index], 4),
                    "fusion_score": round(scores[index], 6),
                },
            }
        )
        if len(selected) == limit:
            break
    return selected, {
        "mode": mode,
        "error_code": error,
        "candidate_count": len(candidates),
        "selected_ids": [m["entry_id"] for m in selected],
        "embedding_model": settings.ark_embedding_model if mode == "hybrid" else None,
    }
