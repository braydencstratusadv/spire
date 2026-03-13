from __future__ import annotations

from dataclasses import dataclass, field

from unidiff import PatchSet


MAX_DIFF_LENGTH = 60000


@dataclass
class DiffFile:
    added: set[int] = field(default_factory=set)
    line_set: set[int] = field(default_factory=set)
    path: str = ''
    text: str = ''


@dataclass
class DiffSet:
    file_map: dict[str, DiffFile] = field(default_factory=dict)

    @property
    def added(self) -> dict[str, set[int]]:
        return {
            path: entry.added
            for path, entry in self.file_map.items()
        }

    @property
    def line_map(self) -> dict[str, set[int]]:
        return {
            path: entry.line_set
            for path, entry in self.file_map.items()
        }

    @property
    def paths(self) -> list[str]:
        return list(self.file_map.keys())

    def filter_by_extension(self, extension_set: tuple[str, ...]) -> str:
        section_list = [
            entry.text
            for path, entry in sorted(self.file_map.items())
            if path.endswith(extension_set)
        ]

        filtered = ''.join(section_list)

        if len(filtered) > MAX_DIFF_LENGTH:
            return (
                filtered[:MAX_DIFF_LENGTH]
                + '\n\n... (diff truncated due to size)'
            )

        return filtered

    def has_extension(self, extension_set: tuple[str, ...]) -> bool:
        return any(
            path.endswith(extension_set)
            for path in self.file_map
        )

    @classmethod
    def from_patch(cls, text: str) -> DiffSet:
        file_map: dict[str, DiffFile] = {}
        patch = PatchSet(text)

        for patched in patch:
            entry = DiffFile(
                path=patched.path,
                text=str(patched),
            )

            for hunk in patched:
                for line in hunk:
                    if line.is_added:
                        entry.added.add(line.target_line_no)
                        entry.line_set.add(line.target_line_no)
                    elif line.is_context:
                        entry.line_set.add(line.target_line_no)

            file_map[patched.path] = entry

        return cls(file_map=file_map)
