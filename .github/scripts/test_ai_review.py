import os
import shutil
import subprocess
import sys

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import dotenv

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(project_root)

dotenv.load_dotenv('development.env')

from ai_code_review import (  # noqa: E402
    CONSENSUS_RUNS,
    CONSENSUS_THRESHOLD,
    DiffSet,
    ReviewConfig,
    RuffLinter,
    _registry,
    comments_from_intel,
    consensus_comments,
)
from ai_code_review.intelligence.prompt import load_instruction_prompt  # noqa: E402
from dandy import Prompt  # noqa: E402

GIT = shutil.which('git') or 'git'
MAX_CONCURRENT_API_CALL = 3
REVIEW_DIR = Path('.review')


@dataclass
class ReviewResult:
    comment_list: list[dict] = field(default_factory=list)
    label: str = ''
    run_count_list: list[int] = field(default_factory=list)


def _single_run(
    config: ReviewConfig,
    diff_set: DiffSet,
    filtered: str,
    run_index: int,
    standard: Prompt,
) -> list[dict]:
    try:
        bot = config.bot(llm_temperature=config.temperature)

        intel = bot.process(
            diff=filtered,
            standard=standard,
        )
    except Exception:
        print(f'  [{config.label}] Run {run_index} failed', file=sys.stderr)
        return []
    else:
        return comments_from_intel(intel, diff_set.line_map, config.prefix)


def run_config(config: ReviewConfig, diff_set: DiffSet) -> ReviewResult:
    filtered = diff_set.filter_by_extension(config.extension_set)

    if not filtered.strip():
        print(f'  [{config.label}] No matching files, skipping.')
        return ReviewResult(label=config.label)

    standard = config.prompt_strategy.load(config.skill_set)

    instruction = load_instruction_prompt(REVIEW_DIR)

    if instruction.snippets:
        print(f'  [{config.label}] Instructions: {REVIEW_DIR}')
        standard.lb()
        standard.prompt(instruction)

    print(f'  [{config.label}] Strategy: {config.prompt_strategy}')
    print(f'  [{config.label}] Standards: {standard.estimated_token_count} tokens')
    print(f'  [{config.label}] Diff: {len(filtered)} chars')
    print(f'  [{config.label}] Running {CONSENSUS_RUNS} consensus passes...')

    all_comment_list: list[list[dict]] = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_API_CALL) as executor:
        future_list = [
            executor.submit(
                _single_run, config, diff_set, filtered, index, standard,
            )
            for index in range(CONSENSUS_RUNS)
        ]

        all_comment_list.extend(
            future.result()
            for future in as_completed(future_list)
        )

    run_count_list = [len(comment_list) for comment_list in all_comment_list]
    comment_list = consensus_comments(all_comment_list)

    print(
        f'  [{config.label}] Runs: {run_count_list},'
        f' consensus: {len(comment_list)}'
        f' ({CONSENSUS_THRESHOLD}/{CONSENSUS_RUNS})',
    )

    return ReviewResult(
        comment_list=comment_list,
        label=config.label,
        run_count_list=run_count_list,
    )


def main() -> None:
    branch = os.environ.get('REVIEW_BRANCH', 'main')

    print(f'Diffing against: {branch}')
    print(f'Consensus: {CONSENSUS_THRESHOLD}/{CONSENSUS_RUNS}')

    diff = subprocess.run(
        [GIT, 'diff', f'{branch}..HEAD'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    if not diff.strip():
        print('Empty diff, nothing to review.')
        return

    diff_set = DiffSet.from_patch(diff)
    print(f'Changed files ({len(diff_set.paths)}): {diff_set.paths}')

    applicable = [
        config for config in _registry
        if config.enabled
        and diff_set.has_extension(config.extension_set)
    ]

    if not applicable:
        print('\nNo applicable reviewers for this diff.')
        return

    print(f'\nRunning {len(applicable)} reviewer(s) concurrently...')

    result_list: list[ReviewResult] = []

    with ThreadPoolExecutor(max_workers=len(applicable)) as executor:
        future_map = {
            executor.submit(run_config, config, diff_set): config
            for config in applicable
        }

        result_list.extend(
            future.result()
            for future in as_completed(future_map)
        )

    print('\n--- Review Results ---')

    for result in result_list:
        if not result.comment_list:
            print(f'\n[{result.label}] No comments.')
            continue

        print(f'\n[{result.label}] {len(result.comment_list)} comment(s):')

        for comment in result.comment_list:
            print(f'  {comment["path"]}:{comment["line"]}')
            print(f'    {comment["body"]}')

    print('\n--- Ruff ---')

    linter = RuffLinter(diff_set=diff_set)
    ruff_comment_list = linter.run()
    print(f'Ruff: {len(ruff_comment_list)} violation(s)')

    for comment in ruff_comment_list:
        print(f'  {comment["path"]}:{comment["line"]}')
        print(f'    {comment["body"]}')


if __name__ == '__main__':
    main()
