from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from tokencat.core.models import (
    CostEstimate,
    PricingCatalog,
    PricingCoverage,
    PricingEntry,
    PricingSourceName,
    ProviderName,
    SessionRecord,
    TokenTotals,
)

APP_DIR_NAME = ".tokencat"
CATALOG_RELATIVE_PATH = Path("pricing") / "catalog.json"
BOOTSTRAP_RELATIVE_PATH = Path("pricing") / "bootstrap.json"
BUILTIN_CATALOG_PACKAGE = "tokencat.pricing"
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

LEGACY_PROVIDER_SOURCE_MAP: dict[str, PricingSourceName] = {
    ProviderName.CODEX.value: "openai",
    ProviderName.GEMINI.value: "gemini",
    ProviderName.COPILOT.value: "github_copilot",
}
DIRECT_SOURCES_BY_PROVIDER: dict[ProviderName, tuple[PricingSourceName, ...]] = {
    ProviderName.CODEX: ("openai",),
    ProviderName.CLAUDE: (),
    ProviderName.GEMINI: ("gemini",),
    ProviderName.COPILOT: ("github_copilot",),
}
OFFICIAL_SOURCES_BY_FAMILY: dict[str, tuple[PricingSourceName, ...]] = {
    "openai": ("openai",),
    "gemini": ("gemini",),
    "anthropic": ("anthropic",),
    "xai": ("xai",),
    "mistral": ("mistral",),
    "deepseek": ("deepseek",),
    "llama": ("meta_llama",),
}
OPENROUTER_NAMESPACES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "gemini": ("google",),
    "anthropic": ("anthropic",),
    "xai": ("x-ai",),
    "mistral": ("mistralai",),
    "deepseek": ("deepseek",),
    "llama": ("meta-llama",),
}
SOURCE_ALIASES: dict[str, PricingSourceName] = {
    "vertex_ai-language-models": "vertex_ai",
    "vertex_ai": "vertex_ai",
    "google_ai_studio": "gemini",
    "gemini": "gemini",
    "openai": "openai",
    "anthropic": "anthropic",
    "xai": "xai",
    "meta_llama": "meta_llama",
    "mistral": "mistral",
    "deepseek": "deepseek",
    "openrouter": "openrouter",
    "github_copilot": "github_copilot",
}
MODEL_ALIASES: dict[str, str] = {
    "gpt-5-codex": "gpt-5",
    "gpt-5.3-codex": "gpt-5.2-codex",
}


@dataclass(slots=True)
class PricingLookupResult:
    entry: PricingEntry
    resolved_model: str
    resolved_source: PricingSourceName
    is_fallback: bool = False


@dataclass(slots=True)
class PricingCandidate:
    pricing_source: PricingSourceName
    model: str
    is_fallback: bool


def user_catalog_path(home: Path | None = None) -> Path:
    base = (home or Path.home()) / APP_DIR_NAME
    return base / CATALOG_RELATIVE_PATH


def pricing_bootstrap_path(home: Path | None = None) -> Path:
    base = (home or Path.home()) / APP_DIR_NAME
    return base / BOOTSTRAP_RELATIVE_PATH


def load_pricing_catalog(home: Path | None = None) -> PricingCatalog:
    cache_path = user_catalog_path(home)
    if cache_path.exists():
        try:
            return _catalog_from_json(json.loads(cache_path.read_text(encoding="utf-8")), source="cache", cache_path=cache_path)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if _should_attempt_bootstrap(home):
        try:
            catalog = refresh_user_pricing_cache(home)
            _write_bootstrap_marker(home, succeeded=True)
            return catalog
        except Exception:
            _write_bootstrap_marker(home, succeeded=False)
    return load_builtin_catalog()


def load_builtin_catalog() -> PricingCatalog:
    raw = resources.files(BUILTIN_CATALOG_PACKAGE).joinpath("catalog.json").read_text(encoding="utf-8")
    return _catalog_from_json(json.loads(raw), source="builtin", cache_path=None)


def save_pricing_catalog(catalog: PricingCatalog, home: Path | None = None) -> Path:
    path = user_catalog_path(home)
    _write_catalog_payload(path, catalog)
    return path


def lookup_pricing_entry(catalog: PricingCatalog, provider: ProviderName, model: str) -> PricingLookupResult | None:
    normalized_model = _normalize_observed_model_name(provider, model)
    for candidate in _pricing_candidates(provider, normalized_model):
        entry = catalog.entries.get((candidate.pricing_source, candidate.model))
        if entry is None or not _has_non_zero_pricing(entry):
            continue
        return PricingLookupResult(
            entry=entry,
            resolved_model=candidate.model,
            resolved_source=candidate.pricing_source,
            is_fallback=candidate.is_fallback,
        )
    return None


def apply_pricing(records: list[SessionRecord], catalog: PricingCatalog | None) -> PricingCoverage | None:
    if catalog is None:
        return None

    coverage = PricingCoverage()
    priced_models: set[tuple[ProviderName, str, str]] = set()
    unknown_models: set[str] = set()

    for record in records:
        record.estimated_cost = CostEstimate()
        record.pricing_model = None
        record.pricing_source = None
        total_tokens = record.token_totals.total or 0
        coverage.total_tokens += total_tokens

        attributed_tokens = 0
        priced_tokens_for_record = 0
        fallback_priced_tokens_for_record = 0
        unknown_tokens_for_record = 0

        primary_usage = record.model_usage.get(record.primary_model) if record.primary_model else None

        for model_name, usage in record.model_usage.items():
            usage.pricing_model = None
            usage.pricing_source = None
            usage.estimated_cost = None
            model_total = usage.tokens.total or usage.tokens.known_total()
            attributed_tokens += model_total
            lookup = lookup_pricing_entry(catalog, record.provider, model_name)

            if lookup is None:
                usage.pricing_status = "unknown_model"
                unknown_models.add(model_name)
                unknown_tokens_for_record += model_total
                coverage.unknown_model_tokens += model_total
                continue

            if usage.tokens.input is None or usage.tokens.output is None:
                usage.pricing_status = "unattributed"
                usage.pricing_model = lookup.resolved_model
                usage.pricing_source = lookup.resolved_source
                continue

            cost = estimate_cost(usage.tokens, lookup.entry)
            usage.estimated_cost = cost
            usage.pricing_model = lookup.resolved_model
            usage.pricing_source = lookup.resolved_source
            usage.pricing_status = "fallback_priced" if lookup.is_fallback or usage.is_fallback_model else "priced"
            record.estimated_cost.add(cost)
            coverage.estimated_cost.add(cost)
            coverage.priced_tokens += model_total
            priced_tokens_for_record += model_total
            if usage.pricing_status == "fallback_priced":
                coverage.fallback_priced_tokens += model_total
                fallback_priced_tokens_for_record += model_total
            priced_models.add((record.provider, usage.pricing_source or "", usage.pricing_model or usage.model))

        unattributed = max(total_tokens - attributed_tokens, 0)
        coverage.unattributed_token_count += unattributed
        coverage.unpriced_tokens += unattributed + unknown_tokens_for_record

        if primary_usage is not None:
            record.pricing_model = primary_usage.pricing_model
            record.pricing_source = primary_usage.pricing_source

        if total_tokens == 0 and not record.model_usage:
            record.pricing_status = "unpriced"
        elif not record.model_usage:
            record.pricing_status = "unattributed"
        elif unattributed > 0 and priced_tokens_for_record == 0 and unknown_tokens_for_record == 0:
            record.pricing_status = "unattributed"
        elif priced_tokens_for_record > 0 and priced_tokens_for_record + unknown_tokens_for_record + unattributed == total_tokens:
            if fallback_priced_tokens_for_record == priced_tokens_for_record:
                record.pricing_status = "fallback_priced"
            elif unknown_tokens_for_record == 0 and unattributed == 0:
                record.pricing_status = "priced"
            else:
                record.pricing_status = "partial"
        elif unknown_tokens_for_record > 0 and priced_tokens_for_record == 0 and unattributed == 0:
            record.pricing_status = "unknown_model"
        elif unknown_tokens_for_record > 0 or unattributed > 0:
            record.pricing_status = "partial"
        else:
            record.pricing_status = "unpriced"

    coverage.priced_model_count = len(priced_models)
    coverage.unknown_models = sorted(unknown_models)
    return coverage


def estimate_cost(tokens: TokenTotals, entry: PricingEntry) -> CostEstimate:
    input_tokens = tokens.input or 0
    cached_tokens = tokens.cached or 0
    non_cached_input_tokens = max(input_tokens - cached_tokens, 0)
    output_tokens = (tokens.output or 0) + (tokens.tool or 0)

    input_cost = non_cached_input_tokens / 1_000_000 * entry.input_per_1m
    cached_rate = entry.cached_input_per_1m if entry.cached_input_per_1m is not None else entry.input_per_1m
    cached_cost = cached_tokens / 1_000_000 * cached_rate
    output_cost = output_tokens / 1_000_000 * entry.output_per_1m
    return CostEstimate(
        input_cost=input_cost,
        cached_input_cost=cached_cost,
        output_cost=output_cost,
        total_cost=input_cost + cached_cost + output_cost,
        currency=entry.currency,
    )


def refresh_user_pricing_cache(home: Path | None = None, *, raw_dataset: dict[str, object] | None = None) -> PricingCatalog:
    dataset = raw_dataset if raw_dataset is not None else _fetch_json(LITELLM_PRICING_URL)
    entries = _normalize_litellm_dataset(dataset)
    if not entries:
        raise ValueError("Could not parse any pricing entries from the structured pricing dataset.")

    refreshed_at = datetime.now().astimezone().isoformat()
    catalog = PricingCatalog(
        source="cache",
        loaded_at=datetime.now().astimezone(),
        entries={(entry.pricing_source, entry.model): entry for entry in entries},
        source_url=LITELLM_PRICING_URL,
        refreshed_at=refreshed_at,
        cache_path=user_catalog_path(home),
    )
    save_pricing_catalog(catalog, home)
    return catalog


def refresh_bundled_pricing_catalog(*, raw_dataset: dict[str, object] | None = None, target_path: Path | None = None) -> PricingCatalog:
    dataset = raw_dataset if raw_dataset is not None else _fetch_json(LITELLM_PRICING_URL)
    entries = _normalize_litellm_dataset(dataset)
    if not entries:
        raise ValueError("Could not parse any pricing entries from the structured pricing dataset.")

    refreshed_at = datetime.now().astimezone().isoformat()
    bundle_path = target_path or _bundled_catalog_path()
    catalog = PricingCatalog(
        source="builtin",
        loaded_at=datetime.now().astimezone(),
        entries={(entry.pricing_source, entry.model): entry for entry in entries},
        source_url=LITELLM_PRICING_URL,
        refreshed_at=refreshed_at,
        cache_path=None,
    )
    _write_catalog_payload(bundle_path, catalog)
    return catalog


def refresh_builtin_pricing(home: Path | None = None, *, raw_dataset: dict[str, object] | None = None) -> PricingCatalog:
    return refresh_user_pricing_cache(home, raw_dataset=raw_dataset)


def _catalog_from_json(payload: dict[str, object], *, source: str, cache_path: Path | None) -> PricingCatalog:
    entries: dict[tuple[PricingSourceName, str], PricingEntry] = {}
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Invalid pricing catalog.")

    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        pricing_source = _catalog_entry_pricing_source(raw)
        if pricing_source is None:
            continue
        entry = PricingEntry(
            pricing_source=pricing_source,
            model=str(raw["model"]),
            input_per_1m=float(raw["input_per_1m"]),
            output_per_1m=float(raw["output_per_1m"]),
            cached_input_per_1m=float(raw["cached_input_per_1m"]) if raw.get("cached_input_per_1m") is not None else None,
            currency=str(raw.get("currency", "USD")),
            effective_date=str(raw.get("effective_date", "")),
            source_url=str(raw.get("source_url", "")),
            notes=_normalize_catalog_notes(raw.get("notes")),
        )
        entries[(entry.pricing_source, entry.model)] = entry

    return PricingCatalog(
        source=source,
        loaded_at=datetime.now().astimezone(),
        entries=entries,
        source_url=str(payload.get("source_url")) if payload.get("source_url") else None,
        refreshed_at=str(payload.get("refreshed_at")) if payload.get("refreshed_at") else None,
        cache_path=cache_path,
    )


def _fetch_json(url: str) -> dict[str, object]:
    try:
        with urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to fetch pricing data from {url}") from exc


def _normalize_litellm_dataset(dataset: dict[str, object]) -> list[PricingEntry]:
    entries: dict[tuple[PricingSourceName, str], PricingEntry] = {}
    today = datetime.now().date().isoformat()

    for raw_name, raw_payload in dataset.items():
        if not isinstance(raw_payload, dict):
            continue
        if not _has_explicit_price_fields(raw_payload):
            continue

        normalized = _normalize_litellm_row(raw_name, raw_payload)
        if normalized is None:
            continue
        pricing_source, canonical_model = normalized

        entry = PricingEntry(
            pricing_source=pricing_source,
            model=canonical_model,
            input_per_1m=_as_number(raw_payload.get("input_cost_per_token")) * 1_000_000,
            output_per_1m=_as_number(raw_payload.get("output_cost_per_token")) * 1_000_000,
            cached_input_per_1m=(
                _as_number(raw_payload.get("cache_read_input_token_cost")) * 1_000_000
                if raw_payload.get("cache_read_input_token_cost") is not None
                else None
            ),
            currency="USD",
            effective_date=today,
            source_url=str(raw_payload.get("source") or LITELLM_PRICING_URL),
            notes=_extract_pricing_notes(raw_name, raw_payload),
        )
        entries[(pricing_source, canonical_model)] = entry

    return sorted(entries.values(), key=lambda item: (item.pricing_source, item.model))


def _pricing_candidates(provider: ProviderName, model: str) -> list[PricingCandidate]:
    family = _infer_model_family(model)
    seen: set[tuple[str, str]] = set()
    candidates: list[PricingCandidate] = []

    def add(source: str, model_key: str, *, is_fallback: bool) -> None:
        key = (source, model_key)
        if key in seen:
            return
        seen.add(key)
        candidates.append(PricingCandidate(pricing_source=source, model=model_key, is_fallback=is_fallback))

    direct_sources = DIRECT_SOURCES_BY_PROVIDER.get(provider, ())
    for source in direct_sources:
        for model_key, used_alias in _model_keys_for_source(source, model, family):
            add(source, model_key, is_fallback=used_alias)

    if family is not None:
        for source in OFFICIAL_SOURCES_BY_FAMILY.get(family, ()):
            for model_key, used_alias in _model_keys_for_source(source, model, family):
                add(source, model_key, is_fallback=True)
        for model_key, used_alias in _model_keys_for_source("openrouter", model, family):
            add("openrouter", model_key, is_fallback=True)

    return candidates


def _model_keys_for_source(source: str, model: str, family: str | None) -> list[tuple[str, bool]]:
    variants: list[tuple[str, bool]] = []
    for variant, used_alias in _observed_model_variants(model):
        if (variant, used_alias) not in variants:
            variants.append((variant, used_alias))

    alias = MODEL_ALIASES.get(model)
    if alias is not None and alias != model:
        for variant, used_alias in _observed_model_variants(alias):
            candidate = (variant, True if variant == alias else used_alias or True)
            if candidate not in variants:
                variants.append(candidate)

    if source == "openrouter":
        if family is None:
            return []
        namespaces = OPENROUTER_NAMESPACES_BY_FAMILY.get(family, ())
        openrouter_variants: list[tuple[str, bool]] = []
        for variant, used_alias in variants:
            if "/" in variant:
                openrouter_variants.append((variant, used_alias))
                continue
            openrouter_variants.extend((f"{namespace}/{variant}", used_alias) for namespace in namespaces)
        return openrouter_variants

    return variants


def _normalize_litellm_row(raw_name: str, raw_payload: dict[str, object]) -> tuple[PricingSourceName, str] | None:
    name = raw_name.strip()
    if not name:
        return None

    if "/" in name:
        source_prefix, remainder = name.split("/", 1)
        normalized_source = _normalize_pricing_source_name(source_prefix)
        if normalized_source == "openrouter":
            return normalized_source, remainder
        if normalized_source is not None:
            return normalized_source, remainder

    litellm_provider = _normalize_pricing_source_name(_as_string(raw_payload.get("litellm_provider")))
    if litellm_provider is not None:
        return litellm_provider, name
    family = _infer_model_family(name)
    if family is not None:
        official_sources = OFFICIAL_SOURCES_BY_FAMILY.get(family, ())
        if official_sources:
            return official_sources[0], name
    return None


def _normalize_pricing_source_name(value: str | None) -> PricingSourceName | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return SOURCE_ALIASES.get(normalized, normalized)


def _normalize_observed_model_name(provider: ProviderName, model: str) -> str:
    normalized = model.strip()
    if provider is ProviderName.COPILOT and normalized.startswith("copilot/"):
        normalized = normalized.split("/", 1)[1]
    return normalized


def _infer_model_family(model: str) -> str | None:
    lower = model.lower()
    family_candidate = lower.rsplit("/", 1)[-1]
    if family_candidate.startswith("gpt-") or "codex" in family_candidate:
        return "openai"
    if family_candidate.startswith("gemini-"):
        return "gemini"
    if family_candidate.startswith("claude-"):
        return "anthropic"
    if family_candidate.startswith("grok-"):
        return "xai"
    if family_candidate.startswith("deepseek"):
        return "deepseek"
    if family_candidate.startswith(("mistral-", "mixtral-", "ministral-", "codestral-")) or "mistral" in family_candidate:
        return "mistral"
    if "llama" in family_candidate:
        return "llama"
    return None


def _observed_model_variants(model: str) -> list[tuple[str, bool]]:
    variants = [(model, False)]
    stripped = _strip_known_model_namespace(model)
    if stripped != model:
        variants.append((stripped, True))
    return variants


def _strip_known_model_namespace(model: str) -> str:
    if "/" not in model:
        return model
    prefix, remainder = model.split("/", 1)
    if prefix in set(SOURCE_ALIASES) or prefix in {
        "anthropic",
        "openai",
        "google",
        "gemini",
        "x-ai",
        "xai",
        "meta-llama",
        "mistralai",
        "deepseek",
        "vertex_ai",
        "bedrock",
        "azure_ai",
        "github_copilot",
    }:
        return remainder
    return model


def _catalog_entry_pricing_source(raw: dict[str, object]) -> PricingSourceName | None:
    explicit = _normalize_pricing_source_name(_as_string(raw.get("pricing_source")))
    if explicit is not None:
        return explicit

    legacy_provider = _as_string(raw.get("provider"))
    if legacy_provider is None:
        return None
    mapped = LEGACY_PROVIDER_SOURCE_MAP.get(legacy_provider)
    if mapped is not None:
        return mapped
    return _normalize_pricing_source_name(legacy_provider)


def _extract_pricing_notes(raw_name: str, raw_payload: dict[str, object]) -> list[str]:
    notes: list[str] = []
    raw_notes = raw_payload.get("notes")
    if isinstance(raw_notes, list):
        notes.extend(str(note) for note in raw_notes)
    elif isinstance(raw_notes, str) and raw_notes.strip():
        notes.append(raw_notes.strip())

    metadata = raw_payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_notes = metadata.get("notes")
        if isinstance(metadata_notes, list):
            notes.extend(str(note) for note in metadata_notes)
        elif isinstance(metadata_notes, str) and metadata_notes.strip():
            notes.append(metadata_notes.strip())

    if not any(note.startswith("litellm_key=") for note in notes):
        notes.append(f"litellm_key={raw_name}")
    return notes


def _normalize_catalog_notes(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(note) for note in value]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _has_explicit_price_fields(payload: dict[str, object]) -> bool:
    return any(payload.get(field) is not None for field in ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost"))


def _as_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _as_number(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _has_non_zero_pricing(entry: PricingEntry) -> bool:
    return any(value > 0 for value in (entry.input_per_1m, entry.output_per_1m, entry.cached_input_per_1m or 0.0))


def _bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parent.parent / "pricing" / "catalog.json"


def _write_catalog_payload(path: Path, catalog: PricingCatalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_url": catalog.source_url,
        "refreshed_at": catalog.refreshed_at or datetime.now().astimezone().isoformat(),
        "entries": [entry.to_dict() for entry in sorted(catalog.entries.values(), key=lambda item: (item.pricing_source, item.model))],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _should_attempt_bootstrap(home: Path | None) -> bool:
    return not pricing_bootstrap_path(home).exists()


def _write_bootstrap_marker(home: Path | None, *, succeeded: bool) -> None:
    marker = pricing_bootstrap_path(home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "attempted_at": datetime.now().astimezone().isoformat(),
        "succeeded": succeeded,
    }
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["refresh-bundled"]:
        refresh_bundled_pricing_catalog()
        return 0
    raise SystemExit("Usage: python -m tokencat.core.pricing refresh-bundled")


if __name__ == "__main__":
    raise SystemExit(main())
