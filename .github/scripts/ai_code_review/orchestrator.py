from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ai_code_review.config import CONSENSUS_RUNS, ReviewConfig, _registry
from ai_code_review.consensus import comments_from_intel, consensus_comments
from ai_code_review.intelligence.prompt import load_instruction_prompt
from ai_code_review.linter import RuffLinter

if TYPE_CHECKING:
    from ai_code_review.diff import DiffSet
    from ai_code_review.github import GitHubClient


MAX_CONCURRENT_API_CALL = 3
REVIEW_DIR = Path('.review')


@dataclass
class ReviewOrchestrator:
    diff_set: DiffSet
    github: GitHubClient

    def _run_config(self, config: ReviewConfig) -> None:
        filtered = self.diff_set.filter_by_extension(config.extension_set)

        if not filtered.strip():
            return

        standard = config.prompt_strategy.load(config.skill_set)

        instruction = load_instruction_prompt(REVIEW_DIR)

        if instruction.snippets:
            standard.lb()
            standard.prompt(instruction)

        all_comment_list: list[list[dict]] = []

        def _single_run(run_index: int) -> list[dict]:
            try:
                bot = config.bot(llm_temperature=config.temperature)

                intel = bot.process(
                    diff=filtered,
                    standard=standard,
                )
            except Exception:
                print(f'{config.label} run {run_index} failed', file=sys.stderr)
                return []
            else:
                return comments_from_intel(
                    intel,
                    self.diff_set.line_map,
                    config.prefix,
                )

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_API_CALL) as executor:
            future_list = [
                executor.submit(_single_run, index)
                for index in range(CONSENSUS_RUNS)
            ]

            all_comment_list.extend(
                future.result()
                for future in as_completed(future_list)
            )

        comment_list = consensus_comments(all_comment_list)

        if comment_list:
            self.github.post_comments(comment_list)

    def run(self) -> None:
        applicable = [
            config for config in _registry
            if config.enabled
            and self.diff_set.has_extension(config.extension_set)
        ]

        if not applicable:
            return

        with ThreadPoolExecutor(max_workers=len(applicable)) as executor:
            future_map = {
                executor.submit(self._run_config, config): config
                for config in applicable
            }

            for future in as_completed(future_map):
                future.result()

    def run_ruff(self) -> None:
        linter = RuffLinter(diff_set=self.diff_set)
        comment_list = linter.run()

        if not comment_list:
            return

        line_list = ['**Ruff**', '']

        for comment in comment_list:
            line_list.append(
                f'- `{comment["path"]}:{comment["line"]}` — {comment["body"]}',
            )

        self.github.post_issue_comment('\n'.join(line_list))
