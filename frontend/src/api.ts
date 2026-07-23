import type {
  ApplicationDetail,
  ApplicationSummary,
  Contact,
  Depth,
  DocumentInfo,
  ExportKind,
  JobRequest,
  MasterProfile,
  PageSize,
  ProfileDetail,
  ProfileSummary,
  ResumeDoc,
  SettingsShape,
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
  patch: { name?: string; contact?: Contact; master_profile?: MasterProfile }
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
  defaultTemplate?: TemplateName
): Promise<ApplicationDetail[]> {
  return request<ApplicationDetail[]>(
    "/applications/batch",
    jsonInit("POST", {
      profile_id: profileId,
      jobs,
      default_depth: defaultDepth,
      default_template: defaultTemplate,
    })
  );
}

export function listApplications(profileId?: number): Promise<ApplicationSummary[]> {
  const qs = profileId !== undefined ? `?profile_id=${profileId}` : "";
  return request<ApplicationSummary[]>(`/applications${qs}`);
}

export function getApplication(id: number): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}`);
}

export function pasteJobText(id: number, text: string): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/paste`, jsonInit("POST", { text }));
}

export function updateContent(
  id: number,
  patch: { resume?: ResumeDoc; cover_letter_md?: string }
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/applications/${id}/content`, jsonInit("PUT", patch));
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

// ---- URL builders (used directly in <a href> / <iframe src>) ----

export function previewUrl(id: number): string {
  return `${API}/applications/${id}/preview`;
}

export function exportUrl(id: number, kind: ExportKind): string {
  return `${API}/applications/${id}/exports/${encodeURIComponent(kind)}`;
}
