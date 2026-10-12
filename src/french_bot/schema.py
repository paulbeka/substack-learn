"""Keep the API schema simple; editorial checks live in validate.py."""

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VocabularyItem(StrictModel):
    french: str
    english: str
    example_french: str


class Question(StrictModel):
    question_french: str
    answer_french: str


class Lesson(StrictModel):
    title_french: str
    title_english: str
    topic: str
    story_french: str
    translation_english: str
    vocabulary: list[VocabularyItem]
    grammar_title: str
    grammar_explanation_english: str
    questions: list[Question]


class EditorReview(StrictModel):
    is_french: bool
    a1_level: bool
    grammar_correct: bool
    translation_faithful: bool
    questions_correct: bool
    grammar_tip_correct: bool
    scenario_distinct: bool
    issues: list[str]

    @property
    def passed(self) -> bool:
        return (
            all(value for value in self.model_dump().values() if isinstance(value, bool))
            and not self.issues
        )


class ValidationReport(StrictModel):
    word_count: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    editor: EditorReview | None = None
    editor_error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.errors
            and not self.editor_error
            and (self.editor is None or self.editor.passed)
        )
