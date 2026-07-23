# Portfolio Scan — a copy-paste prompt for Claude Code

Run [Claude Code](https://claude.com/claude-code) in your **workspace root** — the
folder that contains all your project repos — and paste the prompt below. It will
examine your actual code and git history and produce a **Portfolio Report**: a
truthful, evidence-based breakdown of your projects, formatted so Tailored's
profile builder can digest it.

**How to use the result:**

1. Copy the finished report Claude produces.
2. In Tailored → **Profiles**, paste it as a text document (name it
   `portfolio-report.txt`) alongside your resume uploads.
3. Click **Build**. The profile builder merges the project evidence — with
   skill tags on every bullet — into your master profile.
4. From then on, every application you generate automatically surfaces the
   projects most relevant to that specific posting. A role that mentions
   vector search will pull your retrieval project forward; a data-pipeline
   role will pull your ETL work. That matching is what the tags are for.

Re-run the scan every few months — your codebase keeps evolving even when your
resume doesn't.

---

## The prompt (copy everything below this line)

I want you to build a **Portfolio Report** of my engineering work by examining
the repositories in this workspace. The report will be imported into a resume
tool, so it must be accurate enough to put in front of an employer.

**The honesty rule governs everything:** every claim in the report must be
verifiable from files or git history in this workspace. Dates come from
`git log`, technology claims come from dependency manifests and imports, and
metrics/numbers appear ONLY if they are written in the code, docs, benchmarks,
or configs you actually read. If you cannot point to the file that supports a
sentence, delete the sentence. Never estimate, round up, or embellish. An
under-claimed true bullet beats an impressive maybe.

### Step 1 — Survey

List the candidate project directories. Exclude: cloned third-party repos
(e.g. `github_repos/`), archives and backup dumps, vendored dependencies,
`node_modules`/venvs, and anything that is clearly someone else's work. For
each remaining project, gather quickly: its purpose (README, entry points),
first and last commit dates, commit count, and primary language/stack. Present
me a one-line-per-repo survey table, then select the **8–12 strongest
projects** to deep-dive — judged by substance (real functionality, tests,
architecture), recency, and distinctiveness. Tell me which you picked and why,
then continue.

### Step 2 — Deep dive

For each selected project, actually read the code — not just the README.
Gather:

- **What it really is:** one plain sentence a non-engineer understands, and one
  technical sentence an engineer respects.
- **Activity:** first commit → last commit (months active), rough cadence.
- **Stack:** languages, frameworks, databases, infra — from manifests and
  imports you saw, not guesses.
- **Engineering-quality signals:** test suite (how many tests, do they look
  real?), CI, Docker, migrations, error handling, docs. Only mention what's
  genuinely there.
- **The interesting parts:** the 2–4 things in this codebase a senior engineer
  would find non-trivial — an algorithm, an architecture decision, a hard
  integration, a performance approach. Cite the file paths you read.

### Step 3 — Write the report

Output a single markdown document in EXACTLY this structure:

```
# Portfolio Report — [my name] — [today's date]

## Standout Projects

### [Project name]
One-line: [plain-English purpose]
Active: [YYYY-MM] – [YYYY-MM] ([n] commits)
Stack: [comma-separated technologies]
Evidence:
- [achievement bullet — concrete, specific, verifiable] [tag, tag, tag]
- [3–6 bullets per project, each ending with skill/theme tags in brackets]

## Other Projects (brief)
- [name] — [one-liner] — [stack] — [active dates]

## Cross-Cutting Skills Evidence
- [skill]: demonstrated in [project] ([how]), [project] ([how])
```

Bullet rules: start with a verb; name the technology doing the work; include a
number only when you found it written down; end every bullet with 2–4
lowercase tags in brackets naming the skills/themes it demonstrates (e.g.
`[python, fastapi, testing]`, `[embeddings, search, chromadb]`). The tags are
load-bearing — a downstream tool uses them to match projects to job postings.

### Step 4 — Self-check

Before finishing, re-read every bullet and ask: "which file or git output
proves this?" Delete or soften anything you cannot answer for. Flag anything
that looks private or sensitive (client names, keys, unreleased work) so I can
decide whether to exclude it — reference where it lives; never reproduce
secret values themselves. Then give me the final report ready to copy.

### Step 5 — Save into Tailored (if connected)

**If the Tailored MCP tools are available to you** (you can see
`get_master_profile` and `add_profile_evidence`), close the loop and write the
evidence straight into my master profile — no copy-paste:

1. Call `get_master_profile` (or `list_profiles` if it reports more than one) to
   get the `profile_id`.
2. Map the report into the tool's argument shapes:
   - Each **Standout Project** and each **Other Project** becomes an MPProject:
     `{name, description (the one-liner), url (only if the repo actually has
     one), bullets: [{text, tags}]}` — the Evidence bullets, each carrying the
     skill/theme tags you already assigned.
   - Each **Cross-Cutting Skills Evidence** line becomes a SkillGroup:
     `{label, items: [...]}`.
3. Call `add_profile_evidence(profile_id, projects=[...], skill_groups=[...])`
   (optionally pass a one-line `summary_note` describing the scan). The tool is
   **additive** — it never overwrites what I already have; a project whose name
   already exists is skipped, and a skill group with an existing label has its
   new items merged. Then tell me exactly what it reported as added, skipped, or
   merged.

The honesty rule still governs: only write projects, bullets, and skills you
verified from real files and git history — whatever you save becomes ground
truth for every future resume.

**If the Tailored MCP tools are NOT connected,** just output the finished
markdown report above and stop — I'll paste it into Tailored → **Profiles**
(name it `portfolio-report.txt`) and click **Build**, as described at the top of
this page.
