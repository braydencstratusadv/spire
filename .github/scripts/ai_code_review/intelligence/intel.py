from pydantic import Field

from dandy import BaseIntel


class ReviewCommentIntel(BaseIntel):
    body: str
    line: int
    path: str


class CodeReviewIntel(BaseIntel):
    comment_list: list[ReviewCommentIntel] = Field(default_factory=list)
