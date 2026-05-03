"""
Structured intake question specifications.

Shared between the agent backend (batch answer parsing) and the Streamlit
frontend (form rendering). Each IntakeQuestionSpec carries the question text,
predefined option labels/values, whether multiple selections are allowed, and
a label for the free-text custom input that appears below every question.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntakeOption:
    """A single selectable option within an intake question."""

    label: str
    """Short display label shown in the UI (checkbox / radio text)."""

    value: str
    """Canonical value stored in intake_answers when this option is selected."""


@dataclass(frozen=True)
class IntakeQuestionSpec:
    """Full specification for one intake question."""

    key: str
    """Key used in the intake_answers dict and batch format lines."""

    question: str
    """Human-readable question displayed as the form field label."""

    options: tuple[IntakeOption, ...]
    """Predefined selectable options. Empty tuple means free-text only."""

    multi_select: bool = False
    """If True, render checkboxes; if False, render radio buttons."""

    custom_label: str = "Additional details (optional)"
    """Placeholder / label for the free-text input below the predefined options."""


# ---------------------------------------------------------------------------
# Canonical question set
# ---------------------------------------------------------------------------

INTAKE_QUESTION_SPECS: tuple[IntakeQuestionSpec, ...] = (
    IntakeQuestionSpec(
        key="audience",
        question="Who is the target audience?",
        options=(
            IntakeOption("Senior engineers", "senior engineers"),
            IntakeOption("Junior developers", "junior developers"),
            IntakeOption("Data scientists", "data scientists"),
            IntakeOption("Product / non-technical", "product managers and non-technical readers"),
            IntakeOption("General tech readers", "general tech readers"),
        ),
        multi_select=True,
        custom_label="Other audience (optional)",
    ),
    IntakeQuestionSpec(
        key="tone",
        question="What tone should the post have?",
        options=(
            IntakeOption("Technical deep-dive", "technical deep-dive"),
            IntakeOption("Conversational", "conversational"),
            IntakeOption("Storytelling", "storytelling"),
            IntakeOption("Tutorial-style", "tutorial-style"),
        ),
        multi_select=False,
        custom_label="Additional tone instructions (optional)",
    ),
    IntakeQuestionSpec(
        key="emphasis",
        question="What aspects should be emphasized?",
        options=(
            IntakeOption("Architecture decisions", "architecture decisions"),
            IntakeOption("Performance gains", "performance gains"),
            IntakeOption("Problem-solving process", "problem-solving process"),
            IntakeOption("Specific algorithms", "specific algorithms or data structures"),
            IntakeOption("Code quality", "code quality and best practices"),
        ),
        multi_select=True,
        custom_label="Other emphasis (optional)",
    ),
    IntakeQuestionSpec(
        key="avoid",
        question="Anything that should NOT be mentioned?",
        options=(
            IntakeOption("Internal client names", "internal client names"),
            IntakeOption("Unfinished features", "unfinished or incomplete features"),
            IntakeOption("Team member names", "team member names"),
            IntakeOption("Skip implementation details", "low-level implementation details"),
            IntakeOption("Nothing specific", "nothing specific"),
        ),
        multi_select=True,
        custom_label="Other things to avoid (optional)",
    ),
    IntakeQuestionSpec(
        key="extra_instructions",
        question="Any other context or instructions?",
        options=(),
        multi_select=False,
        custom_label="e.g. Focus on the async pipeline, mention Python 3.12 upgrade...",
    ),
)

# ---------------------------------------------------------------------------
# Batch format
# ---------------------------------------------------------------------------

BATCH_FORMAT_HEADER = "[intake_form_v1]"
"""Magic prefix that marks a human message as a batch intake form submission."""


def format_batch_answers(answers: dict[str, str]) -> str:
    """Serialize intake_answers dict into the batch format string."""
    lines = [BATCH_FORMAT_HEADER]
    for spec in INTAKE_QUESTION_SPECS:
        value = answers.get(spec.key, "")
        lines.append(f"{spec.key}: {value}")
    return "\n".join(lines)


def parse_batch_answers(content: str) -> dict[str, str]:
    """Parse a batch format string into an intake_answers dict.

    Ignores lines that don't contain ':', and strips whitespace from keys/values.
    Returns an empty dict for malformed input.
    """
    result: dict[str, str] = {}
    lines = content.strip().splitlines()
    for line in lines[1:]:  # skip the header line
        if ":" in line:
            key, _, value = line.partition(":")
            stripped_key = key.strip()
            if stripped_key:
                result[stripped_key] = value.strip()
    return result
