from __future__ import annotations

import importlib

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from dandy import Prompt


@dataclass
class BasePromptStrategy(ABC):
    @abstractmethod
    def _base_path(self) -> Path:
        raise NotImplementedError

    def load(self, name_set: set[str]) -> Prompt:
        prompt = Prompt()
        base_path = self._base_path()

        if not base_path.is_dir():
            return prompt

        file_list = sorted(base_path.rglob('*.md'))

        if not file_list:
            return prompt

        prompt.heading('Project Standards and Best Practices')
        prompt.lb()

        for file in file_list:
            content = file.read_text(encoding='utf-8').strip()

            if not content or content == 'pass':
                continue

            if file.parent.name not in name_set and file.stem not in name_set:
                continue

            path = file.relative_to(base_path)
            prompt.sub_heading(str(path))
            prompt.text(
                content,
                triple_backtick=True,
                triple_backtick_label='markdown',
            )
            prompt.lb()

        return prompt


def load_instruction_prompt(directory: Path) -> Prompt:
    prompt = Prompt()

    if not directory.is_dir():
        return prompt

    file_list = sorted(directory.rglob('*.md'))

    if not file_list:
        return prompt

    prompt.heading('Additional Review Instructions')
    prompt.lb()

    for file in file_list:
        content = file.read_text(encoding='utf-8').strip()

        if not content or content == 'pass':
            continue

        path = file.relative_to(directory)
        prompt.sub_heading(str(path))
        prompt.text(
            content,
            triple_backtick=True,
            triple_backtick_label='markdown',
        )
        prompt.lb()

    return prompt


@dataclass
class DirectoryPromptStrategy(BasePromptStrategy):
    directory: Path

    def __str__(self) -> str:
        return f'DirectoryPromptStrategy({self.directory})'

    def _base_path(self) -> Path:
        return self.directory


@dataclass
class PackagePromptStrategy(BasePromptStrategy):
    module: str

    def __str__(self) -> str:
        return f'PackagePromptStrategy({self.module})'

    def _base_path(self) -> Path:
        package = importlib.import_module(self.module)

        if package.__file__ is None:
            return Path()

        return Path(package.__file__).parent
