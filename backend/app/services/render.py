"""Rendering: ResumeDoc -> standalone HTML (Jinja) -> PDF (Playwright) + ATS text.

Templates live in backend/templates/: a shared structural base.css plus one
directory per template (template.html + style.css). CSS is inlined into a
<style> tag so every rendered HTML document is fully standalone.
"""
from __future__ import annotations

import base64
import functools
import html
import json
from dataclasses import dataclass
from pathlib import Path

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas import Contact, ResumeDoc

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
FONTS_DIR = TEMPLATES_DIR / "fonts"

STRUCTURES = ("experience-first", "projects-forward")
_REQUIRED_KEYS = frozenset(
    {"name", "label", "description", "best_for", "structure", "order", "fonts"}
)


class TemplateManifestError(Exception):
    """A template.json is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class FontFace:
    """One @font-face declaration.

    `weight` is a string, not an int, because a variable font covers a range and
    declares it as "400 700". A single-weight static font declares "400".
    """

    family: str
    file: str
    weight: str
    style: str


@dataclass(frozen=True)
class TemplateManifest:
    name: str
    label: str
    description: str
    best_for: str
    structure: str
    order: int
    fonts: tuple[FontFace, ...]


def _parse_manifest(path: Path, directory_name: str) -> TemplateManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateManifestError(f"{path}: cannot read manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise TemplateManifestError(f"{path}: manifest must be a JSON object")
    missing = _REQUIRED_KEYS - set(raw)
    if missing:
        raise TemplateManifestError(
            f"{path}: manifest missing required key(s): {', '.join(sorted(missing))}"
        )
    if raw["name"] != directory_name:
        raise TemplateManifestError(
            f"{path}: manifest name {raw['name']!r} does not match its "
            f"directory {directory_name!r}"
        )
    if raw["structure"] not in STRUCTURES:
        raise TemplateManifestError(
            f"{path}: unknown structure {raw['structure']!r}; "
            f"expected one of {STRUCTURES}"
        )
    if not isinstance(raw["order"], int):
        raise TemplateManifestError(f"{path}: order must be an integer")
    faces: list[FontFace] = []
    for entry in raw["fonts"]:
        try:
            faces.append(
                FontFace(
                    family=entry["family"],
                    file=entry["file"],
                    weight=str(entry["weight"]),
                    style=entry["style"],
                )
            )
        except (TypeError, KeyError) as exc:
            raise TemplateManifestError(
                f"{path}: font entry {entry!r} missing key {exc}"
            ) from exc
    return TemplateManifest(
        name=raw["name"],
        label=raw["label"],
        description=raw["description"],
        best_for=raw["best_for"],
        structure=raw["structure"],
        order=raw["order"],
        fonts=tuple(faces),
    )


def load_registry(templates_dir: Path) -> dict[str, TemplateManifest]:
    """Scan a templates directory and return manifests keyed by name, order-sorted.

    Directories whose name starts with "_" or "." are partials, not templates,
    and "fonts" holds the vendored binaries. Everything else must carry a
    manifest: a directory without one is a template that would silently vanish
    from the UI, which is worse than a loud failure at import.
    """
    manifests: list[TemplateManifest] = []
    for entry in sorted(Path(templates_dir).iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(("_", ".")) or entry.name == "fonts":
            continue
        manifest_path = entry / "template.json"
        if not manifest_path.is_file():
            raise TemplateManifestError(
                f"{entry}: template directory has no template.json"
            )
        manifests.append(_parse_manifest(manifest_path, entry.name))
    manifests.sort(key=lambda m: m.order)
    return {m.name: m for m in manifests}


TEMPLATE_REGISTRY: dict[str, TemplateManifest] = load_registry(TEMPLATES_DIR)
TEMPLATES: tuple[str, ...] = tuple(TEMPLATE_REGISTRY)

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(),
)


@functools.lru_cache(maxsize=None)
def _font_css(template: str) -> str:
    """@font-face declarations with base64-inlined woff2 for one template.

    Cached per process, so a font is base64-encoded once per template per run.
    Inlining matters: render_pdf calls page.set_content(html) with no base URL,
    so an externally referenced font would be silently dropped and the PDF would
    render in a fallback face without any error.
    """
    manifest = TEMPLATE_REGISTRY.get(template)
    if manifest is None:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    blocks: list[str] = []
    for face in manifest.fonts:
        path = FONTS_DIR / face.file
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append(
            "@font-face {\n"
            f"  font-family: '{face.family}';\n"
            f"  font-style: {face.style};\n"
            f"  font-weight: {face.weight};\n"
            "  font-display: block;\n"
            f"  src: url(data:font/woff2;base64,{payload}) format('woff2');\n"
            "}"
        )
    return "\n".join(blocks)


def _load_css(template: str) -> tuple[str, str]:
    """Return (base_css, style_css) for a template; raise on unknown template.

    style_css carries the template's @font-face declarations ahead of its own
    rules, so the single {{ style_css }} slot in template.html stays sufficient.
    """
    if template not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    base_css = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    style_css = (TEMPLATES_DIR / template / "style.css").read_text(encoding="utf-8")
    font_css = _font_css(template)
    if font_css:
        style_css = f"{font_css}\n\n{style_css}"
    return base_css, style_css


def render_resume_html(resume: ResumeDoc, template: str) -> str:
    """Render a ResumeDoc into a fully standalone HTML document."""
    base_css, style_css = _load_css(template)
    tpl = _env.get_template(f"{template}/template.html")
    return tpl.render(resume=resume, base_css=base_css, style_css=style_css)


def render_cover_letter_html(cover_md: str, contact: Contact, template: str) -> str:
    """Markdown cover letter -> standalone HTML in the chosen template's style."""
    base_css, style_css = _load_css(template)
    body_html = markdown_lib.markdown(html.escape(cover_md))
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
