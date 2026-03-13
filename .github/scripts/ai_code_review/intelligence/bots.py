from dandy import Bot, Prompt

from ai_code_review.intelligence.intel import CodeReviewIntel


class _CodeReviewBot(Bot):
    intel_class = CodeReviewIntel

    def process(
        self,
        diff: str,
        standard: Prompt,
    ) -> CodeReviewIntel:
        prompt = Prompt()

        if standard.snippets:
            prompt.prompt(standard)
            prompt.lb()

        prompt.heading('Pull Request Diff')
        prompt.text(diff, triple_backtick=True)

        return self.llm.prompt_to_intel(prompt=prompt)


class BackendReviewBot(_CodeReviewBot):
    guidelines = Prompt().list([
        'Apply the project standards and best practices when reviewing.',
        'Do NOT comment on linting, formatting, or import ordering.'
        ' Ruff handles that.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Focus on model structure, service layer patterns, queryset usage,'
        ' form views, and general Python best practices.',
        'Carefully examine every added or changed line for violations.',
        'Only return an empty comments list if the code strictly'
        ' follows every standard with zero exceptions.',
        'Only reference lines that appear in the diff.',
    ])
    role = 'Senior Django Developer'
    task = (
        'Review the Python and Django code in the provided diff'
        ' against the project standards.'
    )


class FrontendReviewBot(_CodeReviewBot):
    guidelines = Prompt().list([
        'Apply the project template standards and best practices'
        ' when reviewing.',
        'Do NOT comment on linting or formatting.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Focus on template inheritance, component usage,'
        ' Bootstrap structure, and Django Spire patterns.',
        'Carefully examine every added or changed line for violations.',
        'Only return an empty comments list if the templates strictly'
        ' follow every standard with zero exceptions.',
        'Only reference lines that appear in the diff.',
    ])
    role = 'Senior Django Template Developer'
    task = (
        'Review the HTML templates in the provided diff'
        ' against the project standards.'
    )
