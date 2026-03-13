from __future__ import annotations

import json
import os
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_code_review.diff import DiffSet


@dataclass
class RuffLinter:
    diff_set: DiffSet

    def _to_comment_list(self, result_list: list[dict]) -> list[dict]:
        return [
            {
                'body': (
                    f'**Ruff [{violation.get("code", "")}]'
                    f'({violation.get("url", "")})**: '
                    f'{violation.get("message", "")}'
                ),
                'line': violation.get('location', {}).get('row', 0),
                'path': _relative_path(violation.get('filename', '')),
                'side': 'RIGHT',
            }
            for violation in result_list
        ]

    def run(self) -> list[dict]:
        existing = [
            path for path in self.diff_set.paths
            if path.endswith('.py') and Path(path).is_file()
        ]

        if not existing:
            return []

        result = subprocess.run(
            [
                sys.executable, '-m', 'ruff', 'check',
                '--output-format=json', *existing,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if not result.stdout.strip():
            return []

        added = self.diff_set.added

        violation_list = [
            violation
            for violation in json.loads(result.stdout)
            if violation.get('location', {}).get('row', 0)
            in added.get(
                _relative_path(violation.get('filename', '')),
                set(),
            )
        ]

        return self._to_comment_list(violation_list)


def _relative_path(path: str) -> str:
    workspace = os.environ.get('GITHUB_WORKSPACE', '')

    if workspace and path.startswith(workspace):
        return path[len(workspace):].lstrip('/')

    return path
