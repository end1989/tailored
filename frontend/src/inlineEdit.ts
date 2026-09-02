/**
 * Reading a typed-in resume back out of the live preview.
 *
 * The preview iframe renders the real template with edit-mode markup (see
 * backend/templates/_edit.html). Nothing runs inside that frame -- it is
 * sandboxed without allow-scripts -- so this module, running in the parent,
 * reaches into its document and rebuilds a ResumeDoc from it.
 *
 * The rebuild is deliberately structural rather than positional. Deleting a
 * bullet removes its node from the frame, which leaves the remaining
 * data-edit-paths holding stale indices ("bullets.2" now sitting second).
 * Harvest therefore walks the containers still present, in DOM order, and
 * rebuilds every array from what survived; paths are used only to find the base
 * object each container came from, never as positions in the output.
 */
import type {
  CertificationItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  ResumeDoc,
  ResumeSection,
  SkillGroup,
} from "./types";

type Indexable = Record<string, unknown>;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** "Python, Go" -> ["Python", "Go"]. Shared with the skills line. */
export function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

/** Follow a dotted path ("sections.0.items.1") into the base document. */
function resolve(base: ResumeDoc, path: string): unknown {
  let current: unknown = base;
  for (const key of path.split(".")) {
    if (current === null || current === undefined) return undefined;
    current = Array.isArray(current)
      ? current[Number(key)]
      : (current as Indexable)[key];
  }
  return current;
}

/** Text a user typed into one field, trimmed; null when the field is absent. */
function textOf(root: ParentNode, path: string): string | null {
  const el = root.querySelector(`[data-edit-path="${path}"]`);
  return el === null ? null : (el.textContent ?? "").trim();
}

/** Every bullet still present under one entry, in the order it appears. */
function bulletsIn(itemEl: Element): string[] {
  return Array.from(itemEl.querySelectorAll("li"))
    .map((li) => {
      const field = li.querySelector("[data-edit-path]");
      return ((field ?? li).textContent ?? "").trim();
    })
    // An emptied bullet has no meaning and would print as a blank line, so it
    // is dropped. The x marker is the deliberate way to remove one; this is
    // the accidental way, and both end the same.
    .filter((text) => text !== "");
}

/**
 * The node a delete marker removes, or null if `el` is not a delete marker.
 *
 * One rule covers every case: stop at the nearest container that owns an
 * object, or at the list item for a bullet. A bullet marker sits inside an
 * <li> nested in an entry, so the <li> wins; an entry or group marker sits
 * directly in its container; a section marker sits in the heading, so the
 * nearest owner above it is the <section>.
 */
export function removalTarget(el: Element): HTMLElement | null {
  if (!el.hasAttribute("data-delete-path")) return null;
  return el.parentElement?.closest<HTMLElement>("[data-node-path], li") ?? null;
}

function harvestSkillGroups(sectionEl: Element, base: ResumeDoc): SkillGroup[] {
  return Array.from(sectionEl.querySelectorAll<HTMLElement>(".item[data-node-path]")).map(
    (groupEl) => {
      const path = groupEl.dataset.nodePath as string;
      const group = clone(resolve(base, path) as SkillGroup);
      const label = textOf(groupEl, `${path}.label`);
      if (label !== null) group.label = label;
      const items = textOf(groupEl, `${path}.items`);
      if (items !== null) group.items = splitCsv(items);
      return group;
    }
  );
}

function harvestExtras(sectionEl: Element): string[] {
  return Array.from(sectionEl.querySelectorAll("li"))
    .map((li) => {
      const field = li.querySelector("[data-edit-path]");
      return ((field ?? li).textContent ?? "").trim();
    })
    .filter((text) => text !== "");
}

type ItemWithBullets = ExperienceItem | ProjectItem;
type AnyItem = ItemWithBullets | EducationItem | CertificationItem;

function harvestItems(sectionEl: Element, base: ResumeDoc): AnyItem[] {
  return Array.from(sectionEl.querySelectorAll<HTMLElement>(".item[data-node-path]")).map(
    (itemEl) => {
      const path = itemEl.dataset.nodePath as string;
      const item = clone(resolve(base, path) as AnyItem);

      const description = textOf(itemEl, `${path}.description`);
      if (description !== null) (item as ProjectItem).description = description;

      const detail = textOf(itemEl, `${path}.detail`);
      if (detail !== null) (item as EducationItem).detail = detail === "" ? null : detail;

      if ("bullets" in item) {
        (item as ItemWithBullets).bullets = bulletsIn(itemEl);
      }
      return item;
    }
  );
}

/**
 * Rebuild a ResumeDoc from the edit-mode preview document.
 *
 * `base` supplies everything the preview does not carry as editable text:
 * contact details, and the locked Master Profile facts (company, role, dates,
 * institution, credential, certification name). Those are copied through
 * verbatim, which is why a hand edit can never trip the truthfulness guard.
 * Neither argument is mutated.
 */
export function harvestResume(doc: Document, base: ResumeDoc): ResumeDoc {
  const headline = textOf(doc, "headline");
  const summary = textOf(doc, "summary");

  const sections = Array.from(
    doc.querySelectorAll<HTMLElement>("section[data-node-path]")
  ).map((sectionEl) => {
    const path = sectionEl.dataset.nodePath as string;
    const section = clone(resolve(base, path) as ResumeSection);

    const title = textOf(sectionEl, `${path}.title`);
    if (title !== null) section.title = title;

    if (section.type === "skills") {
      section.groups = harvestSkillGroups(sectionEl, base);
    } else if (section.type === "extras") {
      section.items = harvestExtras(sectionEl);
    } else {
      section.items = harvestItems(sectionEl, base) as typeof section.items;
    }
    return section;
  });

  return {
    ...clone(base),
    headline: headline ?? base.headline,
    summary: summary ?? base.summary,
    sections,
  };
}
