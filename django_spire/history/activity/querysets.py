from __future__ import annotations

from django.db.models import QuerySet


class ActivityQuerySet(QuerySet):
    def prefetch_user(self) -> None:
        return self.prefetch_related('user')
