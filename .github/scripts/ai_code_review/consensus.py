from __future__ import annotations

from typing import TYPE_CHECKING

from ai_code_review.config import CONSENSUS_THRESHOLD

if TYPE_CHECKING:
    from ai_code_review.intelligence.intel import CodeReviewIntel


def comments_from_intel(
    intel: CodeReviewIntel,
    line_map: dict[str, set[int]],
    prefix: str,
) -> list[dict]:
    return [
        {
            'body': f'**{prefix}**: {comment.body}',
            'line': comment.line,
            'path': comment.path,
            'side': 'RIGHT',
        }
        for comment in intel.comment_list
        if comment.line in line_map.get(comment.path, set())
    ]


def consensus_comments(
    run_list: list[list[dict]],
) -> list[dict]:
    count_map: dict[tuple[str, int], int] = {}
    seen_map: dict[tuple[str, int], dict] = {}

    for comment_list in run_list:
        for comment in comment_list:
            key = (comment['path'], comment['line'])
            count_map[key] = count_map.get(key, 0) + 1
            seen_map[key] = comment

    return [
        seen_map[key]
        for key, count in count_map.items()
        if count >= CONSENSUS_THRESHOLD
    ]
