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


RESEARCH_STANDARD_SYSTEM = """You are researching a company to help tailor a job application. You have the web_fetch tool, restricted to the company's own website. Fetch the homepage and one or two obvious pages (about, products, careers) within the tool's use limit.

Report only what the company's own site says:
- mission: how the company describes its purpose, in one or two sentences.
- products: the main products or services it offers, as short phrases.
- culture_language: distinctive words and phrases the company uses to describe itself and how it works.
- tech_stack_signals: technologies the site explicitly mentions, if any.
- news: leave empty unless the site itself highlights recent announcements.
- sources: the exact URLs you fetched.

If a fetch fails or the domain is unavailable, fill in what you can from the posting context and leave the rest empty. Never invent facts."""

RESEARCH_DEEP_SYSTEM = """You are researching a company in depth to help tailor a high-priority job application. You have web_search and web_fetch tools with limited uses - spend them deliberately: the company's own site first, then recent news, then engineering blog / tech-stack sources.

Report:
- mission: the company's stated purpose.
- products: the main products or services it offers.
- news: notable items from roughly the last 12 months (funding, launches, partnerships, leadership changes), each as one short sentence.
- tech_stack_signals: languages, frameworks, and infrastructure mentioned in engineering blogs, job postings, talks, or public repositories.
- culture_language: distinctive vocabulary the company uses about itself, its values, and how it works.
- sources: the URL of every page you actually used. Every claim above must be traceable to one of these sources. Never invent facts or URLs."""


def _research_user_content(parsed: ParsedPosting) -> str:
    return (
        "Company: " + parsed.company + "\n"
        "Company domain: " + (parsed.company_domain or "unknown") + "\n"
        "Role being applied for: " + parsed.title + "\n\n"
        "Parsed posting JSON:\n" + parsed.model_dump_json(indent=2)
    )


def research_company(
    parsed: ParsedPosting, depth: str, claude: ClaudeService
) -> tuple[ResearchFindings, UsageInfo] | None:
    if depth == "quick":
        return None
    if depth == "standard":
        tool: dict = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}
        if parsed.company_domain:
            tool["allowed_domains"] = [parsed.company_domain]
        findings, usage = claude.structured(
            task="research_standard",
            system=RESEARCH_STANDARD_SYSTEM,
            user_content=_research_user_content(parsed),
            schema_model=ResearchFindings,
            tools=[tool],
        )
        assert isinstance(findings, ResearchFindings)
        return findings, usage
    if depth == "deep":
        tools: list[dict] = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
        ]
        findings, usage = claude.structured(
            task="research_deep",
            system=RESEARCH_DEEP_SYSTEM,
            user_content=_research_user_content(parsed),
            schema_model=ResearchFindings,
            tools=tools,
        )
        assert isinstance(findings, ResearchFindings)
        return findings, usage
    raise ValueError(f"Unknown research depth: {depth!r}")
