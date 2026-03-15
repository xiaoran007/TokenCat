from __future__ import annotations

from abc import ABC, abstractmethod

from tokencat.core.models import ProviderStatus, ScanFilters, SessionRecord


class ProviderAdapter(ABC):
    @abstractmethod
    def detect(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def scan(self, filters: ScanFilters) -> list[SessionRecord]:
        raise NotImplementedError
