from __future__ import annotations

import hashlib

from tokencat.core.models import ProviderName


def anonymize_session_id(provider: ProviderName, session_id: str) -> str:
    digest = hashlib.sha256(f"{provider}:{session_id}".encode("utf-8")).hexdigest()
    return digest[:12]
