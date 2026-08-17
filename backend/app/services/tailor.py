from __future__ import annotations

from ..schemas import (
    Contact,
    MasterProfile,
    ParsedPosting,
    ResearchFindings,
    ResumeDoc,
    TailorResult,
    UsageInfo,
)
from .claude import ClaudeService
from .render import TEMPLATE_REGISTRY

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
- Respect the template structural hint given in the input: when the hint is "projects-forward", a Projects section leads, before Experience; when it is "experience-first", Experience leads. Include Skills and Education sections whenever the master profile has content for them.

WRITING VOICE (this text must read as the candidate's own writing):
- Plain, concrete, specific. Prefer short sentences to long ones.
- No superlatives, no throat-clearing, no summarising what you just said.
- Prefer the vocabulary of the candidate's field to the vocabulary of recruitment.
- Never use an em dash. Use a comma, a colon, or a full stop.
- Never use an en dash except between two years, as in 2020-2023.
- Never use emoji, curly quotes, or the ellipsis character. Straight quotes and three periods are correct.
- Never write: passionate about, proven track record, results-driven, results-oriented, results-focused, wealth of experience, seamlessly, testament to, delve, tapestry, "I am/I'm excited to", "in today's ... world".
- These rules are checked server-side and a violation is rejected, so follow them the first time.

COVER LETTER (markdown, 3-5 short paragraphs):
- Open specific. When research findings are provided, the first paragraph must reference a concrete finding (mission, product, news item, or culture language). When no research is provided, the first paragraph must reference specific language from the posting itself.
- No boilerplate openings ("I am writing to apply...", "I was excited to see...").
- Ground every claim in facts from the master profile.

TAILORING NOTES:
- In tailoring_notes, briefly explain what you chose to emphasize and why, referencing the posting's requirements.

If a REGENERATION FEEDBACK block is present in the input, treat it as the highest-priority instruction that is consistent with the truthfulness rubric."""


def _structural_hint(template: str) -> str:
    """The section order this template is designed around, from its manifest."""
    manifest = TEMPLATE_REGISTRY.get(template)
    return manifest.structure if manifest is not None else "experience-first"


def tailor_application(
    profile: MasterProfile,
    contact: Contact,
    parsed: ParsedPosting,
    research: ResearchFindings | None,
    template: str,
    claude: ClaudeService,
    feedback: str | None = None,
    voice_sample: str | None = None,
    voice_notes: str | None = None,
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
    if voice_notes:
        parts.append(
            "VOICE DIRECTION FROM THE CANDIDATE (highest-priority style "
            "instruction; explicit direction beats anything inferred below):\n"
            + voice_notes[:2000]
        )
    if voice_sample:
        parts.append(
            "REGISTER REFERENCE - the candidate's own writing, provided so you "
            "can match their register, sentence length, and vocabulary. It is "
            "NOT a source of facts. Every fact must still come from the master "
            "profile:\n" + voice_sample[:2000]
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


def verify_truthfulness(resume: ResumeDoc, profile: MasterProfile) -> list[str]:
    """Structural guard against invented facts.

    Exact-match rules (contract): every ExperienceItem (company, role, start, end)
    must match an MPExperience (company+title exact, start/end exact); every
    EducationItem must match a master-profile education entry on
    (institution, credential); every CertificationItem must match a
    master-profile certification by name. Returns human-readable violation
    strings; an empty list means the resume passes.
    """
    violations: list[str] = []
    allowed_experiences = {
        (e.company, e.title, e.start, e.end) for e in profile.experiences
    }
    allowed_education = {(e.institution, e.credential) for e in profile.education}
    allowed_certifications = {c.name for c in profile.certifications}

    for section in resume.sections:
        if section.type == "experience":
            for item in section.items:
                key = (item.company, item.role, item.start, item.end)
                if key not in allowed_experiences:
                    violations.append(
                        f"Experience '{item.role}' at '{item.company}' "
                        f"({item.start} to {item.end or 'present'}) does not match "
                        "any master-profile experience"
                    )
        elif section.type == "education":
            for item in section.items:
                if (item.institution, item.credential) not in allowed_education:
                    violations.append(
                        f"Education '{item.credential}' at '{item.institution}' "
                        "does not match any master-profile education entry"
                    )
        elif section.type == "certifications":
            for item in section.items:
                if item.name not in allowed_certifications:
                    violations.append(
                        f"Certification '{item.name}' does not match any "
                        "master-profile certification"
                    )
    return violations
