from __future__ import annotations

from ..schemas import (
    Contact,
    MasterProfile,
    ParsedPosting,
    ResearchFindings,
    TailorResult,
    UsageInfo,
)
from .claude import ClaudeService

TAILOR_SYSTEM = """You are an expert resume writer producing a tailored resume and cover letter for one specific job application.

TRUTHFULNESS RUBRIC (absolute, non-negotiable):
- You may SELECT which experiences, projects, and bullets to include.
- You may REORDER sections, roles, and bullets to shift emphasis.
- You may REPHRASE bullet text for clarity and impact.
- You may do NOTHING else. NEVER invent employers, job titles, employment dates, degrees, certifications, tools, or metrics. Every company, role, start date, end date, institution, credential, and certification in your output must appear exactly as it does in the master profile. Every factual claim in every bullet must be supported by the master profile.
- Mirror the posting's vocabulary only where the master profile factually supports it. If the posting asks for something the candidate does not have, omit it - never fabricate it.

RESUME:
- Select the experiences, projects, and bullets most relevant to the parsed posting; trim what does not serve this application.
- headline: one line positioning the candidate for this specific role.
- summary: two to four sentences specific to this candidate and this posting - no generic filler.
- Respect the template structural hint given in the input: the "terminal" template is projects-forward (a Projects section leads, before Experience); every other template is experience-first (Experience leads). Include Skills and Education sections whenever the master profile has content for them.

COVER LETTER (markdown, 3-5 short paragraphs):
- Open specific. When research findings are provided, the first paragraph must reference a concrete finding (mission, product, news item, or culture language). When no research is provided, the first paragraph must reference specific language from the posting itself.
- No boilerplate openings ("I am writing to apply...", "I was excited to see...").
- Ground every claim in facts from the master profile.

TAILORING NOTES:
- In tailoring_notes, briefly explain what you chose to emphasize and why, referencing the posting's requirements.

If a REGENERATION FEEDBACK block is present in the input, treat it as the highest-priority instruction that is consistent with the truthfulness rubric."""


def _structural_hint(template: str) -> str:
    return "projects-forward" if template == "terminal" else "experience-first"


def tailor_application(
    profile: MasterProfile,
    contact: Contact,
    parsed: ParsedPosting,
    research: ResearchFindings | None,
    template: str,
    claude: ClaudeService,
    feedback: str | None = None,
) -> tuple[TailorResult, UsageInfo]:
    parts = [
        "MASTER PROFILE (single source of truth - the only facts you may use):\n"
        + profile.model_dump_json(indent=2),
        "CONTACT (copy into resume.contact unchanged):\n"
        + contact.model_dump_json(indent=2),
        "PARSED JOB POSTING:\n" + parsed.model_dump_json(indent=2),
        "RESEARCH FINDINGS:\n"
        + (research.model_dump_json(indent=2) if research is not None else "none"),
        "TEMPLATE: " + template + " (structural hint: " + _structural_hint(template) + ")",
    ]
    if feedback:
        parts.append(
            "REGENERATION FEEDBACK (apply within the truthfulness rubric):\n" + feedback
        )
    result, usage = claude.structured(
        task="tailor",
        system=TAILOR_SYSTEM,
        user_content="\n\n".join(parts),
        schema_model=TailorResult,
        max_tokens=32000,
    )
    assert isinstance(result, TailorResult)
    return result, usage
