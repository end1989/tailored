from __future__ import annotations

from ..schemas import ParsedPosting, ResearchFindings, UsageInfo
from .claude import ClaudeService

PARSE_POSTING_SYSTEM = """You are a job-posting analyst. You will receive the raw text of a single job posting. Extract a structured summary of it.

Rules:
- title: the job title exactly as the posting states it.
- company: the hiring company's name. If the posting is via a recruiting agency, name the hiring company when identifiable, otherwise the agency.
- company_domain: the company's primary website domain (bare domain like "acme.com" - no scheme, no path, no "www." prefix) if it appears in the posting or is unambiguous from the company name; otherwise null.
- must_haves: hard requirements (skills, years of experience, credentials) the posting treats as mandatory.
- nice_to_haves: preferred or bonus qualifications.
- keywords: the concrete skills, tools, technologies, and domain terms the posting emphasizes - the vocabulary an applicant-tracking system would scan for.
- seniority: one short phrase (for example "senior", "mid-level", "staff", "entry-level"), or null if unclear.
- tone: one short phrase describing the posting's voice (for example "formal corporate", "casual startup", "mission-driven"), or null if unclear.
- Use only information present in the posting text. Never invent requirements."""


def parse_posting(raw_text: str, claude: ClaudeService) -> tuple[ParsedPosting, UsageInfo]:
    parsed, usage = claude.structured(
        task="parse_posting",
        system=PARSE_POSTING_SYSTEM,
        user_content=raw_text,
        schema_model=ParsedPosting,
    )
    assert isinstance(parsed, ParsedPosting)
    return parsed, usage
