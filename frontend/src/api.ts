import type {
  ApplicationDetail,
  ContentSaveResult,
  ApplicationEvent,
  ApplicationSummary,
  Contact,
  Depth,
  DocumentInfo,
  EventKind,
  ExportKind,
  JobRequest,
  MasterProfile,
  PageSize,
  ProfileDetail,
  ProfileSummary,
  ResumeDoc,
  SettingsShape,
  SetupShape,
  Stage,
  TemplateInfo,
  TemplateName,
} from "./types";

const API = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      } else if (body) {
        detail = JSON.stringify(body);
      }
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

// ---- profiles ----

export function listProfiles(): Promise<ProfileSummary[]> {
  return request<ProfileSummary[]>("/profiles");
}

export function createProfile(name: string, contact?: Contact): Promise<ProfileDetail> {
  return request<ProfileDetail>("/profiles", jsonInit("POST", { name, contact }));
}

export function getProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}`);
}

export function updateProfile(
  id: number,
  patch: { name?: string; contact?: Contact; master_profile?: MasterProfile; voice_notes?: string }
): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}`, jsonInit("PUT", patch));
}

export function uploadDocument(
  profileId: number,
  source: File | { filename: string; text: string }
): Promise<DocumentInfo> {
  if (source instanceof File) {
    const form = new FormData();
    form.append("file", source);
    return request<DocumentInfo>(`/profiles/${profileId}/documents`, {
      method: "POST",
      body: form,
    });
  }
  return request<DocumentInfo>(`/profiles/${profileId}/documents`, jsonInit("POST", source));
}

export function buildProfile(id: number): Promise<ProfileDetail> {
  return request<ProfileDetail>(`/profiles/${id}/build`, { method: "POST" });
}

// ---- applications ----

export function createApplications(
  profileId: number,
  jobs: JobRequest[],
  defaultDepth?: Depth,
  defaultTemplate?: TemplateName,
  generate: boolean = true
): Promise<ApplicationDetail[]> {
  return request<ApplicationDetail[]>(
    "/applications/batch",
    jsonInit("POST", {
      profile_id: profileId,
      jobs,
      default_depth: defaultDepth,
      default_template: defaultTemplate,
      generate,
    })
  );
}

export function listApplications(
  profileId?: number,
  opts?: { stage?: Stage; archived?: boolean }
): Promise<ApplicationSummary[]> {
  const params = new URLSearchParams();
  if (profileId !== undefined) params.set("profile_id", String(profileId));
  if (opts?.stage) params.set("stage", opts.stage);
  if (opts?.archived) params.set("archived", "true");
  const qs = params.toString();
  return request<ApplicationSummary[]>(`/applications${qs ? `?${qs}` : ""}`);
}

export function patchApplication(id: number, patch: { stage?: Stage }): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`, jsonInit("PATCH", patch));
}

export function setApplicationTemplate(
  id: number,
  template: string
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(
    `/applications/${id}/template`,
    jsonInit("PATCH", { template })
  );
}

export function archiveApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/archive`, { method: "POST" });
}

export function restoreApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/restore`, { method: "POST" });
}

export function deleteApplication(id: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/applications/${id}`, {
    method: "DELETE",
  });
}

export function generateApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/generate`, { method: "POST" });
}

export function listEvents(id: number): Promise<ApplicationEvent[]> {
  return request<ApplicationEvent[]>(`/applications/${id}/events`);
}

export function addEvent(
  id: number,
  event: { kind: EventKind; body: string; occurred_at?: string }
): Promise<ApplicationEvent> {
  return request<ApplicationEvent>(`/applications/${id}/events`, jsonInit("POST", event));
}

export function deleteEvent(id: number, eventId: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/applications/${id}/events/${eventId}`, {
    method: "DELETE",
  });
}

export function getApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`);
}

export function pasteJobText(id: number, text: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/paste`, jsonInit("POST", { text }));
}

export function updateContent(
  id: number,
  patch: { resume?: ResumeDoc; cover_letter_md?: string; clean?: boolean }
): Promise<ContentSaveResult> {
  return request<ContentSaveResult>(`/applications/${id}/content`, jsonInit("PUT", patch));
}

/**
 * The preview HTML with the inline editing vocabulary in it.
 *
 * Fetched as text and handed to the iframe as srcdoc rather than pointed at
 * with src: a srcdoc frame inherits this origin, so the parent can read its
 * contentDocument to harvest the edits back out.
 */
export async function fetchEditPreview(id: number): Promise<string> {
  const res = await fetch(`${API}/applications/${id}/preview?edit=1`);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.text();
}

export function regenerate(id: number, feedback: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(
    `/applications/${id}/regenerate`,
    jsonInit("POST", { feedback })
  );
}

export async function retryApplication(id: number): Promise<ApplicationDetail> {
  return request(`/applications/${id}/retry`, { method: "POST" });
}

// ---- settings ----

export function getSettings(): Promise<SettingsShape> {
  return request<SettingsShape>("/settings");
}

export function updateSettings(patch: {
  default_template?: TemplateName;
  default_depth?: Depth;
  page_size?: PageSize;
}): Promise<SettingsShape> {
  return request<SettingsShape>("/settings", jsonInit("PUT", patch));
}

// ---- setup ----

export function getSetup(): Promise<SetupShape> {
  return request<SetupShape>("/setup");
}

// ---- templates ----

export function listTemplates(): Promise<TemplateInfo[]> {
  return request<TemplateInfo[]>("/templates");
}

// ---- URL builders (used directly in <a href> / <iframe src>) ----

export function previewUrl(id: number): string {
  return `${API}/applications/${id}/preview`;
}

export function exportUrl(id: number, kind: ExportKind): string {
  return `${API}/applications/${id}/exports/${encodeURIComponent(kind)}`;
}

export function templatePreviewUrl(name: TemplateName): string {
  return `${API}/templates/preview/${name}`;
}
