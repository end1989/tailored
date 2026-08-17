# Tailored — Human Voice Contract — Design Spec

Date: 2026-07-26
Status: approved
Depends on: spec 3 (dashboard job tracker) — reuses its migration helper for
the `Profile.voice_notes` column

## 1. What this is

Generated resumes and cover letters currently carry the typographic and lexical
fingerprints of an LLM: em dashes, curly quotes, the occasional emoji, and the
stock vocabulary of machine-written enthusiasm. A hiring manager reads
"passionate about leveraging cutting-edge solutions" and stops reading. Some
employers run detectors.

This spec makes the generated text read as the candidate's own writing, and
enforces the mechanical part of that rather than requesting it.

## 2. Why enforcement, not instruction

The project's README states its own principle:

> Truthfulness enforced in the data layer, not the prompt. Most AI resume tools
> ask the model nicely not to exaggerate. Tailored rejects any generated resume
> that contains an employer, title, date, degree, or certification not present
> in your Master Profile — a structural check on the write path, so the
> guarantee holds no matter which AI produced the text.

Asking a model nicely not to use em dashes fails in exactly the same way, and
for the same reason: it holds most of the time, which means it does not hold.
It also fails asymmetrically across the two generation paths — Tailored cannot
control which model an MCP client is running.

So the style rules are enforced where truthfulness already is.

`verify_truthfulness` is called from both paths — `pipeline.py:104` for the API
pipeline and `mcp_ops.py:468` for MCP agents. A style check placed beside it
covers both with one implementation, and an MCP agent receives the same
correctable violation list it already receives for truthfulness.

## 3. Decisions

| Decision | Choice |
|---|---|
| Enforcement | Reject on the write path, with a correctable violation list |
| API pipeline on failure | One automatic retry with violations appended, then error |
| MCP on failure | Raise `McpOpsError` with the list; agent corrects and re-calls |
| Ban list scope | Hard-fail only what has near-zero legitimate resume use |
| Voice | Excerpt of the user's own uploaded documents, plus an override field |

## 4. The check

New module `backend/app/services/style.py`:

```python
def check_style(resume: ResumeDoc, cover_md: str) -> list[str]:
    """Human-readable violations of the voice contract. Empty list = clean."""
```

Violations name their location, e.g.
`Experience 'Initech' bullet 2: em dash (—). Rewrite the sentence or use a comma.`
A violation that does not say where it is and what to do instead is a violation
the model will fail to fix on retry.

### 4.1 Fields checked — prose only

| Checked | Not checked |
|---|---|
| `resume.headline` | company, role, institution, credential names |
| `resume.summary` | `start`, `end`, `year` date strings |
| experience bullets | URLs, email, phone, location |
| project `description` and bullets | skill group labels and items |
| education `detail` | |
| extras items | |
| `cover_md` (whole) | |

Two properties follow from this scoping, both load-bearing:

**Template output can never trigger a false positive.** The templates render
date ranges as `{{ item.start }}–{{ item.end }}` with an en dash
(`meridian/template.html:33`). The check runs on the `ResumeDoc` object and the
cover-letter markdown — the model's own output — never on rendered HTML. The
guarantee comes from where the check is wired, not from a regex that has to be
clever about context.

**Facts carried verbatim from the master profile cannot be rejected.** Company
names and date strings come from the profile and are excluded, so a user whose
profile contains `2020–2023` is never blocked by their own data.

### 4.2 Hard-fail: characters

| Rule | Rationale |
|---|---|
| Em dash `—` | The single most recognisable tell. Zero legitimate need; a comma, colon or full stop always works |
| En dash `–` **not between two digits** | `2020–2023` inside a sentence is correct typography and passes; `work – life` does not |
| Emoji and pictographs | No legitimate use in a resume or cover letter |
| Curly quotes `“ ” ‘ ’` | Straight quotes are always acceptable and never a tell. Amendment 2026-08-17: a right single quotation mark between two word characters (Macy's, O'Brien as Word spells them) is allowed; it is carried from names and postings, and rejecting it would block truthful text on every generation for that user or employer. Curly double quotes and the left single quote are still rejected anywhere. |
| Ellipsis character `…` | Use three periods or, better, finish the sentence |
| Non-breaking space, zero-width characters | Invisible, machine-origin, and independently harmful — they corrupt ATS text extraction |

The en-dash rule is stated precisely because the naive version ("no en dashes")
would reject a truthful bullet like `Led the 2020–2023 platform migration`.

### 4.3 Hard-fail: phrases

A deliberately short, curated list, matched case-insensitively on word
boundaries:

```
passionate about          proven track record
results-driven            results-oriented
results-focused           wealth of experience
seamlessly                testament to
delve                     tapestry
I am excited to           I was excited to
I'm excited to
in today's <...> world    in today's <...> landscape
```

Amendment 2026-08-17: `I'm excited to` joins the two spelled-out forms, matched
with either a straight or a curly apostrophe, because the contraction is the
form the model reaches for most often.

### 4.4 What is deliberately *not* banned

`leverage`, `robust`, `scale`, `architect`, `drive`, `spearheaded`,
`cutting-edge`, `meticulous`, and the `not only ... but also` construction.

Every one of these has real, common, pre-LLM use in resumes — `leverage` in
finance, `robust` and `scale` in engineering, `spearheaded` in decades of
management resumes. Banning them would block truthful sentences and push the
model toward stranger phrasing.

**The governing rule: hard-fail only what has near-zero legitimate use in a
resume; everything else is prompt guidance.** A false positive blocks a
truthful resume and burns a retry, which is worse than an occasional stylistic
miss. The list lives in one module constant and is easy to extend once real
output shows what actually leaks.

## 5. Enforcement

### 5.1 API pipeline

In `pipeline.py`, immediately after the existing truthfulness check:

```
violations = check_style(result.resume, result.cover_letter_md)
if violations and not already_retried:
    re-run tailoring once, with the violations appended to the input
elif violations:
    mark error: "Style check failed: ..."
```

One retry, not a loop. A second failure is a signal that something is wrong
with the rules or the model, and burning tokens in a cycle is worse than
surfacing it. The retry cost is one additional tailoring call in the minority
of cases that fail, which is why §4.4 keeps the list tight.

### 5.2 MCP

In `mcp_ops.save_tailored_resume`, beside the existing truthfulness raise:

```
raise McpOpsError(
    "Style check failed:\n- " + "\n- ".join(violations)
    + "\nRewrite the flagged text in the candidate's own plain voice "
      "and call this tool again."
)
```

The agent corrects and re-calls — the pattern it already follows for
truthfulness. No retry counter server-side; the agent owns its own loop.

### 5.3 Ordering

Truthfulness is checked first. A resume that invents an employer should be
reported as inventing an employer, not as having an em dash in the invented
employer's bullet.

## 6. Voice

### 6.1 The user's own writing

`SourceDocument` already stores the extracted text of every resume the user
uploaded during intake (`backend/app/api/profiles.py:147`) — their actual
writing, already in the database, currently used only for profile extraction.

The tailoring input gains an excerpt: the most recent `SourceDocument` for the
profile, truncated to roughly 2000 characters, labelled as a **register
reference**.

The prompt is explicit that it is style-only:

> The following is the candidate's own writing, provided so you can match their
> register, sentence length, and vocabulary. It is NOT a source of facts. Every
> fact must still come from the master profile.

This interacts with truthfulness and the interaction is safe by construction: a
voice sample might tempt a model to lift an employer or a claim from it, and
`verify_truthfulness` structurally rejects exactly that. The existing guard
covers the new risk — which is the argument for having built it structurally in
the first place.

### 6.2 Explicit direction

`Profile.voice_notes: Optional[str]` — free text, e.g. *"Plain and direct. No
salesmanship. Short sentences. Never call myself passionate about anything."*

Added via spec 3's migration helper. Surfaced as a textarea on the profile
screen with a placeholder showing that example.

When present it takes precedence over the inferred register, because explicit
instruction beats inference.

### 6.3 Baseline style rules

Applied regardless of samples, in both the `tailor.py` system prompt and
`get_workflow_guide`:

- Plain, concrete, specific. Short sentences over long ones.
- No superlatives, no throat-clearing, no summarising what you just said.
- Cover letters open on a specific fact about the company or role, never on the
  writer's feelings. (The guide already forbids `"I am writing to apply..."`;
  this extends it.)
- Prefer the vocabulary of the candidate's field to the vocabulary of
  recruitment.
- The character and phrase rules from §4, stated so most runs pass first time.
  Enforcement is the backstop, not the mechanism.

## 7. Testing

- **Each banned character** detected in each checked prose field, and in the
  cover letter.
- **`Led the 2020–2023 migration`** in a bullet passes. The en-dash rule's
  precision is the thing most likely to be broken by a later "simplification",
  so it gets an explicit named test.
- **A date string of `2020–2023`** in `item.start`/`item.end` passes — excluded
  fields are genuinely excluded.
- **Rendered HTML is never checked**: asserted by construction, with a test
  that a template's own en dash does not surface as a violation.
- **§4.4 words pass**: a bullet containing `leverage`, `robust` and
  `spearheaded` is clean. This test exists to stop the ban list creeping.
- **Each banned phrase** detected, case-insensitively, on word boundaries;
  `delved` and `Delve` both caught, `passionately` not caught by the
  `passionate about` rule.
- **API retry**: one style failure triggers exactly one re-run; a second
  failure marks the application `error` with the violations in the message.
- **MCP**: `save_tailored_resume` raises with the list and does not persist the
  resume.
- **Ordering**: a resume that is both untruthful and stylistically flawed
  reports the truthfulness violation.
- **Voice sample does not leak facts**: a `SourceDocument` naming an employer
  absent from the master profile, with a resume that uses it, is still rejected
  by `verify_truthfulness`.
- **`voice_notes`** reaches the tailoring input when set.

## 8. Out of scope

- Re-checking or rewriting resumes generated before this ships.
- Scoring against a third-party AI detector, or any claim about detector
  outcomes. The goal is text that reads as human, not a number.
- Per-job tone selection (formal / casual).
- Applying the check to research findings or parsed postings — neither is
  user-facing prose.
- A UI for editing the ban list. It is a module constant.

## 9. Risks

**Over-banning is the main failure mode.** A list that grows without discipline
starts rejecting truthful, well-written sentences, and every rejection costs a
retry. §4.4 and its accompanying test exist specifically to hold that line.

**Curly quotes are the most arguable rule.** They are genuinely better
typography in a serif template, and a human writer using Word produces them
too. They are banned because straight quotes are always acceptable in a resume,
making the rule free to satisfy — but it is the first rule to revisit if the
output suffers.

**Retry cost is real.** One extra tailoring call per failing generation. Kept
acceptable by making the prompt carry the rules so most runs pass first time,
and by capping retries at one.
