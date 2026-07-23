import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import {
  buildProfile,
  createProfile,
  getProfile,
  listProfiles,
  updateProfile,
  uploadDocument,
} from "../api";
import type {
  MasterProfile,
  MPCertification,
  MPEducation,
  MPExperience,
  MPProject,
  ProfileDetail,
  ProfileSummary,
  SkillGroup,
  TaggedBullet,
  UsageInfo,
} from "../types";

const emptyMP: MasterProfile = {
  summary_notes: "",
  experiences: [],
  projects: [],
  skills: [],
  education: [],
  certifications: [],
  extras: [],
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export default function ProfileScreen() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProfileDetail | null>(null);
  const [mp, setMp] = useState<MasterProfile>(emptyMP);
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [building, setBuilding] = useState(false);
  const [buildUsage, setBuildUsage] = useState<UsageInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function selectProfile(id: number) {
    setSelectedId(id);
    const d = await getProfile(id);
    setDetail(d);
    setMp({ ...emptyMP, ...d.master_profile });
  }

  async function refreshProfiles(selectId?: number) {
    const list = await listProfiles();
    setProfiles(list);
    const target = selectId ?? selectedId ?? (list.length > 0 ? list[0].id : null);
    if (target !== null) {
      await selectProfile(target);
    }
  }

  useEffect(() => {
    refreshProfiles().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- typed master-profile editor helpers ----

  function updateExperience(idx: number, patch: Partial<MPExperience>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) => (i === idx ? { ...e, ...patch } : e)),
    }));
  }

  function addExperience() {
    setMp((m) => ({
      ...m,
      experiences: [
        ...m.experiences,
        { company: "", title: "", start: "", end: null, location: null, bullets: [] },
      ],
    }));
  }

  function removeExperience(idx: number) {
    setMp((m) => ({ ...m, experiences: m.experiences.filter((_, i) => i !== idx) }));
  }

  function updateBullet(expIdx: number, bulletIdx: number, patch: Partial<TaggedBullet>) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx
          ? {
              ...e,
              bullets: e.bullets.map((b, j) => (j === bulletIdx ? { ...b, ...patch } : b)),
            }
          : e
      ),
    }));
  }

  function addBullet(expIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: [...e.bullets, { text: "", tags: [] }] } : e
      ),
    }));
  }

  function removeBullet(expIdx: number, bulletIdx: number) {
    setMp((m) => ({
      ...m,
      experiences: m.experiences.map((e, i) =>
        i === expIdx ? { ...e, bullets: e.bullets.filter((_, j) => j !== bulletIdx) } : e
      ),
    }));
  }

  function updateSkillGroup(idx: number, patch: Partial<SkillGroup>) {
    setMp((m) => ({
      ...m,
      skills: m.skills.map((g, i) => (i === idx ? { ...g, ...patch } : g)),
    }));
  }

  function addSkillGroup() {
    setMp((m) => ({ ...m, skills: [...m.skills, { label: "", items: [] }] }));
  }

  function removeSkillGroup(idx: number) {
    setMp((m) => ({ ...m, skills: m.skills.filter((_, i) => i !== idx) }));
  }

  function updateEducation(idx: number, patch: Partial<MPEducation>) {
    setMp((m) => ({
      ...m,
      education: m.education.map((ed, i) => (i === idx ? { ...ed, ...patch } : ed)),
    }));
  }

  function addEducation() {
    setMp((m) => ({
      ...m,
      education: [...m.education, { institution: "", credential: "", year: null, detail: null }],
    }));
  }

  function removeEducation(idx: number) {
    setMp((m) => ({ ...m, education: m.education.filter((_, i) => i !== idx) }));
  }

  function updateCertification(idx: number, patch: Partial<MPCertification>) {
    setMp((m) => ({
      ...m,
      certifications: m.certifications.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  }

  function addCertification() {
    setMp((m) => ({
      ...m,
      certifications: [...m.certifications, { name: "", issuer: null, year: null }],
    }));
  }

  function removeCertification(idx: number) {
    setMp((m) => ({ ...m, certifications: m.certifications.filter((_, i) => i !== idx) }));
  }

  function updateProject(idx: number, patch: Partial<MPProject>) {
    setMp((m) => ({
      ...m,
      projects: m.projects.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    }));
  }

  function addProject() {
    setMp((m) => ({
      ...m,
      projects: [...m.projects, { name: "", description: "", url: null, bullets: [] }],
    }));
  }

  function removeProject(idx: number) {
    setMp((m) => ({ ...m, projects: m.projects.filter((_, i) => i !== idx) }));
  }

  function updateExtra(idx: number, value: string) {
    setMp((m) => ({ ...m, extras: m.extras.map((x, i) => (i === idx ? value : x)) }));
  }

  function addExtra() {
    setMp((m) => ({ ...m, extras: [...m.extras, ""] }));
  }

  function removeExtra(idx: number) {
    setMp((m) => ({ ...m, extras: m.extras.filter((_, i) => i !== idx) }));
  }

  // ---- actions ----

  async function handleCreate() {
    if (newName.trim() === "") return;
    try {
      const d = await createProfile(newName.trim(), {
        name: newName.trim(),
        email: newEmail.trim(),
        links: [],
      });
      setNewName("");
      setNewEmail("");
      await refreshProfiles(d.id);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    if (selectedId === null || !e.target.files || e.target.files.length === 0) return;
    try {
      await uploadDocument(selectedId, e.target.files[0]);
      e.target.value = "";
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handlePasteDoc() {
    if (selectedId === null || pasteText.trim() === "") return;
    try {
      await uploadDocument(selectedId, {
        filename: pasteName.trim() !== "" ? pasteName.trim() : "pasted.txt",
        text: pasteText,
      });
      setPasteName("");
      setPasteText("");
      await selectProfile(selectedId);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleBuild() {
    if (selectedId === null) return;
    setBuilding(true);
    setError(null);
    try {
      const d = await buildProfile(selectedId);
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
      setBuildUsage(d.usage ?? null);
    } catch (err) {
      setError(String(err));
    } finally {
      setBuilding(false);
    }
  }

  async function handleSave() {
    if (selectedId === null) return;
    setSaving(true);
    setError(null);
    try {
      const d = await updateProfile(selectedId, { master_profile: mp });
      setDetail(d);
      setMp({ ...emptyMP, ...d.master_profile });
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1>Profiles</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="card-title">Your profiles</div>
        <div className="row">
          {profiles.map((p) => (
            <button
              key={p.id}
              className={p.id === selectedId ? "btn btn-primary" : "btn"}
              onClick={() => selectProfile(p.id).catch((e) => setError(String(e)))}
            >
              {p.name}
            </button>
          ))}
          {profiles.length === 0 && <span className="muted">No profiles yet — create one below.</span>}
        </div>
        <div className="row">
          <input
            className="input"
            placeholder="Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            className="input"
            placeholder="Email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <button className="btn" onClick={handleCreate}>
            Create profile
          </button>
        </div>
      </div>

      {detail && (
        <>
          <h2>{detail.name}</h2>

          <div className="card">
            <div className="card-title">Documents</div>
            <ul>
              {detail.documents.map((d) => (
                <li key={d.id}>
                  {d.filename} <span className="muted">({d.kind})</span>
                </li>
              ))}
            </ul>
            {detail.documents.length === 0 && (
              <p className="muted">Upload your existing resumes and notes to build a master profile.</p>
            )}
            <div className="field">
              <label className="field-label">Upload file (.pdf, .docx, .txt)</label>
              <input type="file" accept=".pdf,.docx,.txt" onChange={handleFile} />
            </div>
            <div className="field">
              <label className="field-label">Or paste text</label>
              <input
                className="input"
                placeholder="Document name"
                value={pasteName}
                onChange={(e) => setPasteName(e.target.value)}
              />
              <textarea
                className="textarea"
                placeholder="Paste resume or notes text"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
              <button className="btn" onClick={handlePasteDoc}>
                Add pasted text
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Build</div>
            <p className="muted">
              Structures every document above into the master profile with one Claude call.
              Re-running replaces the current structured profile.
            </p>
            <button className="btn btn-primary" onClick={handleBuild} disabled={building}>
              {building && <span className="spinner" />}
              {building ? " Building..." : "Build master profile"}
            </button>
            {buildUsage && (
              <p className="muted">
                Done — {buildUsage.input_tokens} tokens in, {buildUsage.output_tokens} out, cost $
                {buildUsage.cost_usd.toFixed(4)}
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-title">Master profile</div>

            <div className="field">
              <label className="field-label">Summary notes</label>
              <textarea
                className="textarea"
                value={mp.summary_notes}
                onChange={(e) => setMp({ ...mp, summary_notes: e.target.value })}
              />
            </div>

            <h3>Experiences</h3>
            {mp.experiences.map((exp, i) => (
              <div className="card" key={i}>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Company"
                    value={exp.company}
                    onChange={(e) => updateExperience(i, { company: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="Title"
                    value={exp.title}
                    onChange={(e) => updateExperience(i, { title: e.target.value })}
                  />
                </div>
                <div className="row">
                  <input
                    className="input"
                    placeholder="Start (YYYY-MM)"
                    value={exp.start}
                    onChange={(e) => updateExperience(i, { start: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="End (blank = present)"
                    value={exp.end ?? ""}
                    onChange={(e) =>
                      updateExperience(i, { end: e.target.value === "" ? null : e.target.value })
                    }
                  />
                  <input
                    className="input"
                    placeholder="Location"
                    value={exp.location ?? ""}
                    onChange={(e) =>
                      updateExperience(i, {
                        location: e.target.value === "" ? null : e.target.value,
                      })
                    }
                  />
                </div>
                {exp.bullets.map((b, j) => (
                  <div className="row" key={j}>
                    <input
                      className="input"
                      placeholder="Bullet text"
                      value={b.text}
                      onChange={(e) => updateBullet(i, j, { text: e.target.value })}
                    />
                    <input
                      className="input"
                      placeholder="tags, comma, separated"
                      value={b.tags.join(", ")}
                      onChange={(e) => updateBullet(i, j, { tags: splitCsv(e.target.value) })}
                    />
                    <button className="btn btn-danger" onClick={() => removeBullet(i, j)}>
                      Remove
                    </button>
                  </div>
                ))}
                <div className="row">
                  <button className="btn btn-ghost" onClick={() => addBullet(i)}>
                    Add bullet
                  </button>
                  <button className="btn btn-danger" onClick={() => removeExperience(i)}>
                    Remove experience
                  </button>
                </div>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExperience}>
              Add experience
            </button>

            <h3>Skills</h3>
            {mp.skills.map((g, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Group label"
                  value={g.label}
                  onChange={(e) => updateSkillGroup(i, { label: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="items, comma, separated"
                  value={g.items.join(", ")}
                  onChange={(e) => updateSkillGroup(i, { items: splitCsv(e.target.value) })}
                />
                <button className="btn btn-danger" onClick={() => removeSkillGroup(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addSkillGroup}>
              Add skill group
            </button>

            <h3>Education</h3>
            {mp.education.map((ed, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Institution"
                  value={ed.institution}
                  onChange={(e) => updateEducation(i, { institution: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Credential"
                  value={ed.credential}
                  onChange={(e) => updateEducation(i, { credential: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={ed.year ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Detail"
                  value={ed.detail ?? ""}
                  onChange={(e) =>
                    updateEducation(i, { detail: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeEducation(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addEducation}>
              Add education
            </button>

            <h3>Certifications</h3>
            {mp.certifications.map((c, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Certification name"
                  value={c.name}
                  onChange={(e) => updateCertification(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Issuer"
                  value={c.issuer ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { issuer: e.target.value === "" ? null : e.target.value })
                  }
                />
                <input
                  className="input"
                  placeholder="Year"
                  value={c.year ?? ""}
                  onChange={(e) =>
                    updateCertification(i, { year: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeCertification(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addCertification}>
              Add certification
            </button>

            <h3>Projects</h3>
            {mp.projects.map((p, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Project name"
                  value={p.name}
                  onChange={(e) => updateProject(i, { name: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="Description"
                  value={p.description}
                  onChange={(e) => updateProject(i, { description: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="URL"
                  value={p.url ?? ""}
                  onChange={(e) =>
                    updateProject(i, { url: e.target.value === "" ? null : e.target.value })
                  }
                />
                <button className="btn btn-danger" onClick={() => removeProject(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addProject}>
              Add project
            </button>

            <h3>Additional</h3>
            {mp.extras.map((x, i) => (
              <div className="row" key={i}>
                <input
                  className="input"
                  placeholder="Extra item"
                  value={x}
                  onChange={(e) => updateExtra(i, e.target.value)}
                />
                <button className="btn btn-danger" onClick={() => removeExtra(i)}>
                  Remove
                </button>
              </div>
            ))}
            <button className="btn btn-ghost" onClick={addExtra}>
              Add extra
            </button>

            <div className="row" style={{ marginTop: "1.25rem" }}>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save master profile"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
