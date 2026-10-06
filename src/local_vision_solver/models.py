from typing import Literal
from pydantic import Field
from .config import StrictModel


class Question(StrictModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    page_numbers: list[int] = Field(min_length=1)


class Uncertainty(StrictModel):
    page_number: int = Field(ge=1)
    description: str = Field(min_length=1)
    alternatives: list[str]
    # Fractional bounds on the EXIF-oriented original; null if location unknown.
    crop_box: list[float] | None


class Reading(StrictModel):
    detected_language: Literal["en", "ru", "kk"]
    subject: Literal["mathematics", "physics", "computer_science", "english",
                     "kazakh", "geography", "mixed"]
    task_type: str = Field(min_length=1)
    requires_math_rendering: bool
    page_order: list[int] = Field(min_length=1)
    problem_text: str = Field(min_length=1)
    questions: list[Question] = Field(min_length=1)
    uncertainties: list[Uncertainty]
    sufficient_information: bool
    warnings: list[str]


class Block(StrictModel):
    kind: Literal["text", "math", "code"]
    content: str = Field(min_length=1)


class NumericCheck(StrictModel):
    label: str
    left: str
    right: str
    absolute_tolerance: float = Field(ge=0, le=0.01)


class Draft(StrictModel):
    detected_language: Literal["en", "ru", "kk"]
    answered_question_ids: list[str] = Field(min_length=1)
    # Empty for writing tasks; the first card then begins the full response.
    final_answer: list[Block]
    solution: list[Block] = Field(min_length=1)
    numeric_checks: list[NumericCheck]
    warnings: list[str]
    confidence: float = Field(ge=0, le=1)


class Audit(StrictModel):
    verdict: Literal["accept", "revise", "reread", "unreadable"]
    question_understanding_checked: bool
    all_questions_answered: bool
    units_checked: bool
    answer_options_checked: bool
    original_images_checked: bool
    issues: list[str]
    correction_instructions: str

