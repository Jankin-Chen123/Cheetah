"""Text-only Ark embeddings, fixed host, bounded responses, no raw provider errors."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from app.integrations.bailian import ModelUnavailable, NoRedirect


def embed_text(settings, text):
    if not settings.ark_api_key:
        raise ModelUnavailable("EMBEDDING_NOT_CONFIGURED")
    url = urlparse(settings.ark_base_url)
    if (
        url.scheme != "https"
        or url.hostname != "ark.cn-beijing.volces.com"
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ModelUnavailable("EMBEDDING_ENDPOINT_NOT_ALLOWED")
    if not text.strip() or len(text) > 6000:
        raise ModelUnavailable("EMBEDDING_INPUT_INVALID")
    multimodal = settings.ark_embedding_api == "multimodal"
    payload = {
        "model": settings.ark_embedding_model,
        "input": [{"type": "text", "text": text}] if multimodal else [text],
        "encoding_format": "float",
    }
    request = Request(
        settings.ark_base_url.rstrip("/")
        + ("/embeddings/multimodal" if multimodal else "/embeddings"),
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings.ark_api_key.get_secret_value(),
        },
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = json.loads(response.read(2000000))["data"]
        vector = data[0]["embedding"] if isinstance(data, list) else data["embedding"]
        if not isinstance(vector, list) or not 2 <= len(vector) <= 8192:
            raise ValueError()
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector):
            raise ValueError()
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0 or not math.isfinite(norm):
            raise ValueError()
        return [v / norm for v in vector]
    except HTTPError as error:
        raise ModelUnavailable(f"EMBEDDING_HTTP_{error.code}") from None
    except (URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
        raise ModelUnavailable("EMBEDDING_UNAVAILABLE") from None
