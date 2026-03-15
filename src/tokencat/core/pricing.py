from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from tokencat.core.models import CostEstimate, PricingCatalog, PricingCoverage, PricingEntry, ProviderName, SessionRecord, TokenTotals

APP_DIR_NAME = ".tokencat"
CATALOG_RELATIVE_PATH = Path("pricing") / "catalog.json"
BUILTIN_CATALOG_PACKAGE = "tokencat.pricing"
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
SUPPORTED_PREFIXES = {
    ProviderName.CODEX: ("openai/", "azure/", "openrouter/openai/"),
    ProviderName.GEMINI: ("gemini/", "vertex_ai/", "google_ai_studio/"),
}
PRICE_ALIASES = {
    ProviderName.CODEX: {
        "gpt-5-codex": "gpt-5",
        "gpt-5.3-codex": "gpt-5.2-codex",
    },
    ProviderName.GEMINI: {},
}


@dataclass(slots=True)
class PricingLookupResult:
    entry: PricingEntry
    resolved_model: str
    is_fallback: bool = False


def user_catalog_path(home: Path | None = None) -> Path:
    base = (home or Path.home()) / APP_DIR_NAME
    return base / CATALOG_RELATIVE_PATH


def load_pricing_catalog(home: Path | None = None) -> PricingCatalog:
    cache_path = user_catalog_path(home)
    if cache_path.exists():
        try:
            return _catalog_from_json(json.loads(cache_path.read_text(encoding="utf-8")), source="cache", cache_path=cache_path)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return load_builtin_catalog()


def load_builtin_catalog() -> PricingCatalog:
    raw = resources.files(BUILTIN_CATALOG_PACKAGE).joinpath("catalog.json").read_text(encoding="utf-8")
    return _catalog_from_json(json.loads(raw), source="builtin", cache_path=None)


def save_pricing_catalog(catalog: PricingCatalog, home: Path | None = None) -> Path:
    path = user_catalog_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_url": catalog.source_url,
        "refreshed_at": catalog.refreshed_at or datetime.now().astimezone().isoformat(),
        "entries": [entry.to_dict() for entry in sorted(catalog.entries.values(), key=lambda item: (item.provider.value, item.model))],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def lookup_pricing_entry(catalog: PricingCatalog, provider: ProviderName, model: str) -> PricingLookupResult | None:
    direct = catalog.entries.get((provider, model))
    if direct is not None and _has_non_zero_pricing(direct):
        return PricingLookupResult(entry=direct, resolved_model=direct.model, is_fallback=False)

    alias = PRICE_ALIASES.get(provider, {}).get(model)
    if alias is not None:
        aliased = catalog.entries.get((provider, alias))
        if aliased is not None and _has_non_zero_pricing(aliased):
            return PricingLookupResult(entry=aliased, resolved_model=alias, is_fallback=True)

    if direct is not None:
        return PricingLookupResult(entry=direct, resolved_model=direct.model, is_fallback=False)
    return None


def apply_pricing(records: list[SessionRecord], catalog: PricingCatalog | None) -> PricingCoverage | None:
    if catalog is None:
        return None

    coverage = PricingCoverage()
    priced_models: set[tuple[ProviderName, str]] = set()
    unknown_models: set[str] = set()

    for record in records:
        record.estimated_cost = CostEstimate()
        record.pricing_model = None
        total_tokens = record.token_totals.total or 0
        coverage.total_tokens += total_tokens

        attributed_tokens = 0
        priced_tokens_for_record = 0
        fallback_priced_tokens_for_record = 0
        unknown_tokens_for_record = 0

        primary_usage = record.model_usage.get(record.primary_model) if record.primary_model else None

        for model_name, usage in record.model_usage.items():
            model_total = usage.tokens.total or usage.tokens.known_total()
            attributed_tokens += model_total
            lookup = lookup_pricing_entry(catalog, record.provider, model_name)

            if lookup is None:
                usage.pricing_status = "unknown_model"
                usage.pricing_model = None
                usage.estimated_cost = None
                unknown_models.add(model_name)
                unknown_tokens_for_record += model_total
                coverage.unknown_model_tokens += model_total
                continue

            if usage.tokens.input is None or usage.tokens.output is None:
                usage.pricing_status = "unattributed"
                usage.pricing_model = lookup.resolved_model
                usage.estimated_cost = None
                continue

            cost = estimate_cost(usage.tokens, lookup.entry)
            usage.estimated_cost = cost
            usage.pricing_model = lookup.resolved_model
            usage.pricing_status = "fallback_priced" if lookup.is_fallback or usage.is_fallback_model else "priced"
            record.estimated_cost.add(cost)
            coverage.estimated_cost.add(cost)
            coverage.priced_tokens += model_total
            priced_tokens_for_record += model_total
            if usage.pricing_status == "fallback_priced":
                coverage.fallback_priced_tokens += model_total
                fallback_priced_tokens_for_record += model_total
            priced_models.add((record.provider, usage.pricing_model or usage.model))

        unattributed = max(total_tokens - attributed_tokens, 0)
        coverage.unattributed_token_count += unattributed
        coverage.unpriced_tokens += unattributed + unknown_tokens_for_record

        if primary_usage is not None:
            record.pricing_model = primary_usage.pricing_model

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


def refresh_builtin_pricing(home: Path | None = None, *, raw_dataset: dict[str, object] | None = None) -> PricingCatalog:
    dataset = raw_dataset if raw_dataset is not None else _fetch_json(LITELLM_PRICING_URL)
    entries = _normalize_litellm_dataset(dataset)
    if not entries:
        raise ValueError("Could not parse any pricing entries from the structured pricing dataset.")

    refreshed_at = datetime.now().astimezone().isoformat()
    catalog = PricingCatalog(
        source="cache",
        loaded_at=datetime.now().astimezone(),
        entries={(entry.provider, entry.model): entry for entry in entries},
        source_url=LITELLM_PRICING_URL,
        refreshed_at=refreshed_at,
        cache_path=user_catalog_path(home),
    )
    save_pricing_catalog(catalog, home)
    return catalog


def _catalog_from_json(payload: dict[str, object], *, source: str, cache_path: Path | None) -> PricingCatalog:
    entries: dict[tuple[ProviderName, str], PricingEntry] = {}
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Invalid pricing catalog.")

    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        provider = ProviderName(raw["provider"])
        entry = PricingEntry(
            provider=provider,
            model=str(raw["model"]),
            input_per_1m=float(raw["input_per_1m"]),
            output_per_1m=float(raw["output_per_1m"]),
            cached_input_per_1m=float(raw["cached_input_per_1m"]) if raw.get("cached_input_per_1m") is not None else None,
            currency=str(raw.get("currency", "USD")),
            effective_date=str(raw.get("effective_date", "")),
            source_url=str(raw.get("source_url", "")),
            notes=[str(note) for note in raw.get("notes", [])],
        )
        entries[(provider, entry.model)] = entry

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
    entries: dict[tuple[ProviderName, str], PricingEntry] = {}
    today = datetime.now().date().isoformat()

    for raw_name, raw_payload in dataset.items():
        if not isinstance(raw_payload, dict):
            continue
        input_cost = _as_number(raw_payload.get("input_cost_per_token"))
        output_cost = _as_number(raw_payload.get("output_cost_per_token"))
        cached_cost = _as_number(raw_payload.get("cache_read_input_token_cost"))
        provider, canonical_model = _classify_model_name(raw_name)
        if provider is None or canonical_model is None:
            continue

        entry = PricingEntry(
            provider=provider,
            model=canonical_model,
            input_per_1m=input_cost * 1_000_000,
            output_per_1m=output_cost * 1_000_000,
            cached_input_per_1m=(cached_cost * 1_000_000) if cached_cost is not None else None,
            currency="USD",
            effective_date=today,
            source_url=LITELLM_PRICING_URL,
        )
        entries[(provider, canonical_model)] = entry

    return sorted(entries.values(), key=lambda item: (item.provider.value, item.model))


def _classify_model_name(raw_name: str) -> tuple[ProviderName | None, str | None]:
    normalized = raw_name.strip()
    for provider, prefixes in SUPPORTED_PREFIXES.items():
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break

    lower = normalized.lower()
    if lower.startswith("gpt-") or "codex" in lower:
        return ProviderName.CODEX, normalized
    if lower.startswith("gemini-"):
        return ProviderName.GEMINI, normalized
    return None, None


def _as_number(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _has_non_zero_pricing(entry: PricingEntry) -> bool:
    return any(value > 0 for value in (entry.input_per_1m, entry.output_per_1m, entry.cached_input_per_1m or 0.0))
