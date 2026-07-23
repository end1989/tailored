"""Rendering: ResumeDoc -> standalone HTML (Jinja) -> PDF (Playwright) + ATS text.

Templates live in backend/templates/: a shared structural base.css plus one
directory per template (template.html + style.css). CSS is inlined into a
<style> tag so every rendered HTML document is fully standalone.
"""
from __future__ import annotations

from pathlib import Path

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas import Contact, ResumeDoc

TEMPLATES = ("meridian", "slate", "terminal", "signal")
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


def _load_css(template: str) -> tuple[str, str]:
    """Return (base_css, style_css) for a template; raise on unknown template."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    base_css = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    return base_css, style_css


def render_resume_html(resume: ResumeDoc, template: str) -> str:
    """Render a ResumeDoc into a fully standalone HTML document."""
    base_css, style_css = _load_css(template)
    tpl = _env.get_template(f"{template}/template.html")
    return tpl.render(resume=resume, base_css=base_css, style_css=style_css)


def render_cover_letter_html(cover_md: str, contact: Contact, template: str) -> str:
    """Markdown cover letter -> standalone HTML in the chosen template's style."""
    base_css, style_css = _load_css(template)
    body_html = markdown_lib.markdown(cover_md)
    tpl = _env.get_template("cover_letter.html")
    return tpl.render(
        body_html=body_html, contact=contact, base_css=base_css, style_css=style_css
    )


def render_ats_text(resume: ResumeDoc) -> str:
    """Deterministic ATS-safe plain text. No tabs, no wrapping.

    Layout:
      NAME (upper)
      email | phone | location   (present fields only, " | "-joined)
      label: url                 (one line per link)
      <blank>
      HEADLINE (upper)
      summary
      <blank before each section>
      TITLE (upper)
      '=' * len(title)
      items (per-type formats; see per-branch code below)
    Ends with exactly one trailing newline.
    """
    lines: list[str] = []
    c = resume.contact
    lines.append(c.name.upper())
    contact_bits = [b for b in (c.email, c.phone, c.location) if b]
    if contact_bits:
        lines.append(" | ".join(contact_bits))
    for link in c.links:
        lines.append(f"{link.label}: {link.url}")
    lines.append("")
    lines.append(resume.headline.upper())
    lines.append(resume.summary)

    for section in resume.sections:
        lines.append("")
        lines.append(section.title.upper())
        lines.append("=" * len(section.title))
        if section.type == "experience":
            for item in section.items:
                head = (
                    f"{item.role.upper()} — {item.company} "
                    f"({item.start}–{item.end or 'present'})"
                )
                if item.location:
                    head += f" [{item.location}]"
                lines.append(head)
                for bullet in item.bullets:
                    lines.append(f"- {bullet}")
        elif section.type == "projects":
            for item in section.items:
                head = item.name
                if item.description:
                    head += f" — {item.description}"
                lines.append(head)
                for bullet in item.bullets:
                    lines.append(f"- {bullet}")
                if item.url:
                    lines.append(item.url)
        elif section.type == "skills":
            for group in section.groups:
                lines.append(f"{group.label}: {', '.join(group.items)}")
        elif section.type == "education":
            for item in section.items:
                line = f"{item.credential}, {item.institution}"
                if item.year:
                    line += f" ({item.year})"
                if item.detail:
                    line += f" — {item.detail}"
                lines.append(line)
        elif section.type == "certifications":
            for item in section.items:
                line = item.name
                if item.issuer:
                    line += f" — {item.issuer}"
                if item.year:
                    line += f" ({item.year})"
                lines.append(line)
        elif section.type == "extras":
            for item in section.items:
                lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def render_pdf(html: str, out_path: Path, page_size: str = "Letter") -> None:
    """Print HTML to PDF via headless Chromium (Playwright sync API)."""
    from playwright.sync_api import sync_playwright  # lazy: fast tests never need it

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(out_path),
                format=page_size,
                print_background=True,
                margin={
                    "top": "0.5in",
                    "right": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.5in",
                },
            )
        finally:
            browser.close()


def export_application(
    application_id: int,
    resume: ResumeDoc,
    cover_md: str,
    contact: Contact,
    template: str,
    data_dir: Path,
    page_size: str = "Letter",
) -> Path:
    """Write the five export files for an application; return the export dir.

    Files under <data_dir>/exports/<application_id>/:
      resume.pdf, resume.html, resume.txt (ATS), cover_letter.pdf,
      cover_letter.txt (the raw markdown).
    """
    export_dir = Path(data_dir) / "exports" / str(application_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    resume_html = render_resume_html(resume, template)
    cover_html = render_cover_letter_html(cover_md, contact, template)
    ats_text = render_ats_text(resume)

    (export_dir / "resume.html").write_text(resume_html, encoding="utf-8")
    (export_dir / "resume.txt").write_text(ats_text, encoding="utf-8")
    (export_dir / "cover_letter.txt").write_text(cover_md, encoding="utf-8")
    render_pdf(resume_html, export_dir / "resume.pdf", page_size=page_size)
    render_pdf(cover_html, export_dir / "cover_letter.pdf", page_size=page_size)
    return export_dir
