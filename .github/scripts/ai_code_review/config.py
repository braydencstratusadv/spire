from __future__ import annotations

import os

from dataclasses import dataclass

from ai_code_review.intelligence.bots import BackendReviewBot, FrontendReviewBot, _CodeReviewBot
from ai_code_review.intelligence.prompt import BasePromptStrategy, PackagePromptStrategy


CONSENSUS_RUNS = int(os.environ.get('AI_REVIEW_CONSENSUS_RUNS', '3'))
CONSENSUS_THRESHOLD = int(os.environ.get('AI_REVIEW_CONSENSUS_THRESHOLD', '1'))

SPIRE_OPENCODE_MODULE = 'django_spire.core.management.commands.spire_opencode_pkg'

_registry: list[ReviewConfig] = []


@dataclass
class ReviewConfig:
    bot: type[_CodeReviewBot]
    enabled_var: str
    extension_set: tuple[str, ...]
    label: str
    prefix: str
    prompt_strategy: BasePromptStrategy
    skill_set: set[str]
    temperature: float = 0.0

    @property
    def enabled(self) -> bool:
        return os.environ.get(self.enabled_var, 'true').lower() == 'true'


def register(*config_list: ReviewConfig) -> None:
    _registry.extend(config_list)


register(
    ReviewConfig(
        bot=BackendReviewBot,
        enabled_var='AI_REVIEW_BACKEND',
        extension_set=('.py',),
        label='Stratus Backend Bot',
        prefix='Stratus Backend Bot',
        prompt_strategy=PackagePromptStrategy(
            module=SPIRE_OPENCODE_MODULE,
        ),
        skill_set={
            'best-practices', 'form_views', 'models', 'queryset',
            'seeding', 'service-layer', 'service_layer',
        },
    ),
    ReviewConfig(
        bot=FrontendReviewBot,
        enabled_var='AI_REVIEW_FRONTEND',
        extension_set=('.html', '.css', '.js'),
        label='Stratus Frontend Bot',
        prefix='Stratus Frontend Bot',
        prompt_strategy=PackagePromptStrategy(
            module=SPIRE_OPENCODE_MODULE,
        ),
        skill_set={
            'badge_templates', 'best-practices', 'button-template',
            'container-template', 'detail_templates', 'form_templates',
            'list_templates', 'tab-template', 'table-template', 'template',
        },
    ),
)
