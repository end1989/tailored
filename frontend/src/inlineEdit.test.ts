import { describe, expect, it } from "vitest";
import { harvestResume, removalTarget, splitCsv } from "./inlineEdit";
import type { ResumeDoc } from "./types";

const BASE: ResumeDoc = {
  contact: { name: "Jane Doe", email: "jane@example.com", phone: null, location: null, links: [] },
  headline: "Senior Backend Engineer",
  summary: "Eight years building APIs.",
  sections: [
    {
      type: "experience",
      title: "Experience",
      items: [
        {
          company: "Initech",
          role: "Staff Engineer",
          start: "2021",
          end: null,
          location: "Remote",
          bullets: ["Led the migration.", "Cut p95 latency 40%."],
        },
        {
          company: "Acme",
          role: "Backend Engineer",
          start: "2018",
          end: "2021",
          bullets: ["Built billing."],
        },
      ],
    },
    {
      type: "skills",
      title: "Skills",
      groups: [
        { label: "Languages", items: ["Python", "Go"] },
        { label: "Data", items: ["Postgres"] },
      ],
    },
    {
      type: "projects",
      title: "Projects",
      items: [
        {
          name: "VerifyMyAI",
          description: "Detects prompt injection.",
          url: "https://example.com",
          bullets: ["Open source."],
        },
      ],
    },
    {
      type: "education",
      title: "Education",
      items: [
        { institution: "State University", credential: "BS CS", year: "2014", detail: "Distributed systems." },
      ],
    },
    { type: "extras", title: "Additional", items: ["Mentor", "Speaker"] },
  ],
};

/** The markup the edit-mode template emits, in miniature. */
function editDoc(): Document {
  const html = `
    <header>
      <h1 data-locked>Jane Doe</h1>
      <p contenteditable="plaintext-only" data-edit-path="headline">Senior Backend Engineer</p>
      <p contenteditable="plaintext-only" data-edit-path="summary">Eight years building APIs.</p>
    </header>
    <section data-node-path="sections.0">
      <h2><span data-edit-path="sections.0.title">Experience</span><span class="edit-del" data-delete-path="sections.0">x</span></h2>
      <div class="item" data-node-path="sections.0.items.0"><span class="edit-del" data-delete-path="sections.0.items.0">x</span>
        <div class="item-head"><span class="primary" data-locked>Staff Engineer</span></div>
        <ul class="bullets">
          <li><span data-edit-path="sections.0.items.0.bullets.0">Led the migration.</span><span class="edit-del" data-delete-path="sections.0.items.0.bullets.0">x</span></li>
          <li><span data-edit-path="sections.0.items.0.bullets.1">Cut p95 latency 40%.</span><span class="edit-del" data-delete-path="sections.0.items.0.bullets.1">x</span></li>
        </ul>
      </div>
      <div class="item" data-node-path="sections.0.items.1"><span class="edit-del" data-delete-path="sections.0.items.1">x</span>
        <div class="item-head"><span class="primary" data-locked>Backend Engineer</span></div>
        <ul class="bullets">
          <li><span data-edit-path="sections.0.items.1.bullets.0">Built billing.</span><span class="edit-del" data-delete-path="sections.0.items.1.bullets.0">x</span></li>
        </ul>
      </div>
    </section>
    <section data-node-path="sections.1">
      <h2><span data-edit-path="sections.1.title">Skills</span></h2>
      <div class="item skill-group" data-node-path="sections.1.groups.0">
        <span class="skill-label"><span data-edit-path="sections.1.groups.0.label">Languages</span>:</span>
        <span class="skill-items"><span data-edit-path="sections.1.groups.0.items">Python, Go</span></span><span class="edit-del" data-delete-path="sections.1.groups.0">x</span>
      </div>
      <div class="item skill-group" data-node-path="sections.1.groups.1">
        <span class="skill-label"><span data-edit-path="sections.1.groups.1.label">Data</span>:</span>
        <span class="skill-items"><span data-edit-path="sections.1.groups.1.items">Postgres</span></span><span class="edit-del" data-delete-path="sections.1.groups.1">x</span>
      </div>
    </section>
    <section data-node-path="sections.2">
      <h2><span data-edit-path="sections.2.title">Projects</span></h2>
      <div class="item" data-node-path="sections.2.items.0">
        <div class="item-head">
          <span class="primary" data-locked>VerifyMyAI</span>
          <span class="secondary" data-edit-path="sections.2.items.0.description">Detects prompt injection.</span>
        </div>
        <ul class="bullets">
          <li><span data-edit-path="sections.2.items.0.bullets.0">Open source.</span></li>
        </ul>
      </div>
    </section>
    <section data-node-path="sections.3">
      <h2><span data-edit-path="sections.3.title">Education</span></h2>
      <div class="item" data-node-path="sections.3.items.0">
        <div class="item-head"><span class="primary" data-locked>BS CS</span></div>
        <p class="detail" data-edit-path="sections.3.items.0.detail">Distributed systems.</p>
      </div>
    </section>
    <section data-node-path="sections.4">
      <h2><span data-edit-path="sections.4.title">Additional</span></h2>
      <ul class="bullets extras">
        <li><span data-edit-path="sections.4.items.0">Mentor</span><span class="edit-del" data-delete-path="sections.4.items.0">x</span></li>
        <li><span data-edit-path="sections.4.items.1">Speaker</span><span class="edit-del" data-delete-path="sections.4.items.1">x</span></li>
      </ul>
    </section>`;
  return new DOMParser().parseFromString(`<html><body>${html}</body></html>`, "text/html");
}

function textAt(doc: Document, path: string): HTMLElement {
  const el = doc.querySelector<HTMLElement>(`[data-edit-path="${path}"]`);
  if (!el) throw new Error(`no element at ${path}`);
  return el;
}

describe("splitCsv", () => {
  it("trims and drops empties", () => {
    expect(splitCsv(" Python ,, Go,")).toEqual(["Python", "Go"]);
  });
});

describe("harvestResume", () => {
  it("returns the base document unchanged when nothing was typed", () => {
    expect(harvestResume(editDoc(), BASE)).toEqual(BASE);
  });

  it("does not mutate the base document", () => {
    const doc = editDoc();
    textAt(doc, "summary").textContent = "Rewritten.";
    harvestResume(doc, BASE);
    expect(BASE.summary).toBe("Eight years building APIs.");
  });

  it("picks up edits to headline, summary and section titles", () => {
    const doc = editDoc();
    textAt(doc, "headline").textContent = "Staff Engineer";
    textAt(doc, "summary").textContent = "Nine years building APIs.";
    textAt(doc, "sections.0.title").textContent = "Where I have worked";
    const out = harvestResume(doc, BASE);
    expect(out.headline).toBe("Staff Engineer");
    expect(out.summary).toBe("Nine years building APIs.");
    expect(out.sections[0].title).toBe("Where I have worked");
  });

  it("picks up bullet, description, detail and extras edits", () => {
    const doc = editDoc();
    textAt(doc, "sections.0.items.0.bullets.1").textContent = "Cut p95 latency by half.";
    textAt(doc, "sections.2.items.0.description").textContent = "Finds injection attacks.";
    textAt(doc, "sections.3.items.0.detail").textContent = "Focus on databases.";
    textAt(doc, "sections.4.items.1").textContent = "Conference speaker";
    const out = harvestResume(doc, BASE);
    const experience = out.sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items[0].bullets).toEqual(["Led the migration.", "Cut p95 latency by half."]);
    const projects = out.sections[2];
    if (projects.type !== "projects") throw new Error("wrong section");
    expect(projects.items[0].description).toBe("Finds injection attacks.");
    const education = out.sections[3];
    if (education.type !== "education") throw new Error("wrong section");
    expect(education.items[0].detail).toBe("Focus on databases.");
    const extras = out.sections[4];
    if (extras.type !== "extras") throw new Error("wrong section");
    expect(extras.items).toEqual(["Mentor", "Conference speaker"]);
  });

  it("splits an edited skills line back into items", () => {
    const doc = editDoc();
    textAt(doc, "sections.1.groups.0.items").textContent = "Python, Go, Rust";
    textAt(doc, "sections.1.groups.1.label").textContent = "Storage";
    const out = harvestResume(doc, BASE);
    const skills = out.sections[1];
    if (skills.type !== "skills") throw new Error("wrong section");
    expect(skills.groups[0].items).toEqual(["Python", "Go", "Rust"]);
    expect(skills.groups[1].label).toBe("Storage");
  });

  it("carries locked facts through untouched", () => {
    const out = harvestResume(editDoc(), BASE);
    const experience = out.sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items[0]).toMatchObject({
      company: "Initech",
      role: "Staff Engineer",
      start: "2021",
      end: null,
      location: "Remote",
    });
  });

  it("trims whitespace the browser leaves behind", () => {
    const doc = editDoc();
    textAt(doc, "summary").textContent = "  Padded.  ";
    expect(harvestResume(doc, BASE).summary).toBe("Padded.");
  });

  // --- deletion: harvest rebuilds arrays from what survives in the DOM ---

  it("drops a bullet whose node was removed, without shifting the others", () => {
    const doc = editDoc();
    removalTarget(doc.querySelector('[data-delete-path="sections.0.items.0.bullets.0"]')!)!.remove();
    const experience = harvestResume(doc, BASE).sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items[0].bullets).toEqual(["Cut p95 latency 40%."]);
    expect(experience.items[1].bullets).toEqual(["Built billing."]);
  });

  it("drops a whole entry and keeps the rest of the section", () => {
    const doc = editDoc();
    removalTarget(doc.querySelector('[data-delete-path="sections.0.items.0"]')!)!.remove();
    const experience = harvestResume(doc, BASE).sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items).toHaveLength(1);
    expect(experience.items[0].company).toBe("Acme");
  });

  it("drops a whole section", () => {
    const doc = editDoc();
    removalTarget(doc.querySelector('[data-delete-path="sections.0"]')!)!.remove();
    const out = harvestResume(doc, BASE);
    expect(out.sections.map((s) => s.type)).toEqual([
      "skills",
      "projects",
      "education",
      "extras",
    ]);
  });

  it("drops a skills group", () => {
    const doc = editDoc();
    removalTarget(doc.querySelector('[data-delete-path="sections.1.groups.0"]')!)!.remove();
    const skills = harvestResume(doc, BASE).sections[1];
    if (skills.type !== "skills") throw new Error("wrong section");
    expect(skills.groups.map((g) => g.label)).toEqual(["Data"]);
  });

  it("drops an extras item", () => {
    const doc = editDoc();
    removalTarget(doc.querySelector('[data-delete-path="sections.4.items.0"]')!)!.remove();
    const extras = harvestResume(doc, BASE).sections[4];
    if (extras.type !== "extras") throw new Error("wrong section");
    expect(extras.items).toEqual(["Speaker"]);
  });

  it("drops a bullet the user emptied out", () => {
    const doc = editDoc();
    textAt(doc, "sections.0.items.0.bullets.0").textContent = "   ";
    const experience = harvestResume(doc, BASE).sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items[0].bullets).toEqual(["Cut p95 latency 40%."]);
  });

  it("keeps an emptied summary, which is a legitimate empty field", () => {
    const doc = editDoc();
    textAt(doc, "summary").textContent = "";
    expect(harvestResume(doc, BASE).summary).toBe("");
  });

  it("nulls an emptied education detail rather than storing a blank", () => {
    const doc = editDoc();
    textAt(doc, "sections.3.items.0.detail").textContent = "";
    const education = harvestResume(doc, BASE).sections[3];
    if (education.type !== "education") throw new Error("wrong section");
    expect(education.items[0].detail).toBeNull();
  });

  it("survives every entry being deleted", () => {
    const doc = editDoc();
    doc.querySelectorAll('[data-node-path^="sections.0.items."]').forEach((el) => el.remove());
    const experience = harvestResume(doc, BASE).sections[0];
    if (experience.type !== "experience") throw new Error("wrong section");
    expect(experience.items).toEqual([]);
  });
});

describe("removalTarget", () => {
  it("stops at the list item for a bullet marker", () => {
    const doc = editDoc();
    const marker = doc.querySelector('[data-delete-path="sections.0.items.0.bullets.0"]')!;
    expect(removalTarget(marker)!.tagName).toBe("LI");
  });

  it("stops at the entry for an entry marker", () => {
    const doc = editDoc();
    const marker = doc.querySelector('[data-delete-path="sections.0.items.0"]')!;
    expect(removalTarget(marker)!.getAttribute("data-node-path")).toBe("sections.0.items.0");
  });

  it("stops at the section for a section marker in the heading", () => {
    const doc = editDoc();
    const marker = doc.querySelector('[data-delete-path="sections.0"]')!;
    expect(removalTarget(marker)!.tagName).toBe("SECTION");
  });

  it("returns null for anything that is not a marker", () => {
    const doc = editDoc();
    expect(removalTarget(textAt(doc, "summary"))).toBeNull();
  });
});
