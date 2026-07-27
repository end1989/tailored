// ---- enums / literals (verbatim from the backend contract) ----
export type Depth = "quick" | "standard" | "deep" | "external"; // "external" = MCP mode (agent did the research)
export type TemplateName = "meridian" | "slate" | "terminal" | "signal";
export type AppStatus =
  | "not_started"
  | "queued"
  | "fetching"
  | "researching"
  | "tailoring"
  | "rendering"
  | "ready"
  | "needs_paste"
  | "error";

export type Stage =
  | "saved"
  | "drafted"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export type EventKind =
  | "applied"
  | "callback"
  | "interview"
  | "offer"
  | "rejection"
  | "followup"
  | "note";

export interface ApplicationEvent {
  id: number;
  application_id: number;
  kind: EventKind;
  body: string;
  occurred_at: string;
  created_at: string;
}

export type PageSize = "Letter" | "A4";
export type ExportKind =
  | "resume.pdf"
  | "resume.html"
  | "resume.txt"
  | "cover_letter.pdf"
  | "cover_letter.txt";

// ---- contact ----
export interface LinkItem {
  label: string;
  url: string;
}

export interface Contact {
  name: string;
  email: string;
  phone?: string | null;
  location?: string | null;
  links: LinkItem[];
}

// ---- master profile ----
export interface TaggedBullet {
  text: string;
  tags: string[];
}

export interface MPExperience {
  company: string;
  title: string;
  start: string;
  end?: string | null;
  location?: string | null;
  bullets: TaggedBullet[];
}

export interface MPProject {
  name: string;
  description: string;
  url?: string | null;
  bullets: TaggedBullet[];
}

export interface SkillGroup {
  label: string;
  items: string[];
}

export interface MPEducation {
  institution: string;
  credential: string;
  year?: string | null;
  detail?: string | null;
}

export interface MPCertification {
  name: string;
  issuer?: string | null;
  year?: string | null;
}

export interface MasterProfile {
  summary_notes: string;
  experiences: MPExperience[];
  projects: MPProject[];
  skills: SkillGroup[];
  education: MPEducation[];
  certifications: MPCertification[];
  extras: string[];
}

// ---- posting analysis + research ----
export interface ParsedPosting {
  title: string;
  company: string;
  company_domain?: string | null;
  must_haves: string[];
  nice_to_haves: string[];
  keywords: string[];
  seniority?: string | null;
  tone?: string | null;
}

export interface ResearchFindings {
  mission: string;
  products: string[];
  news: string[];
  tech_stack_signals: string[];
  culture_language: string[];
  sources: string[];
}

// ---- resume document (renderer contract) ----
export interface ExperienceItem {
  company: string;
  role: string;
  start: string;
  end?: string | null;
  location?: string | null;
  bullets: string[];
}

export interface ProjectItem {
  name: string;
  description: string;
  url?: string | null;
  bullets: string[];
}

export interface EducationItem {
  institution: string;
  credential: string;
  year?: string | null;
  detail?: string | null;
}

export interface CertificationItem {
  name: string;
  issuer?: string | null;
  year?: string | null;
}

export interface ExperienceSection {
  type: "experience";
  title: string;
  items: ExperienceItem[];
}

export interface ProjectsSection {
  type: "projects";
  title: string;
  items: ProjectItem[];
}

export interface SkillsSection {
  type: "skills";
  title: string;
  groups: SkillGroup[];
}

export interface EducationSection {
  type: "education";
  title: string;
  items: EducationItem[];
}

export interface CertificationsSection {
  type: "certifications";
  title: string;
  items: CertificationItem[];
}

export interface ExtrasSection {
  type: "extras";
  title: string;
  items: string[];
}

export type ResumeSection =
  | ExperienceSection
  | ProjectsSection
  | SkillsSection
  | EducationSection
  | CertificationsSection
  | ExtrasSection;

export interface ResumeDoc {
  contact: Contact;
  headline: string;
  summary: string;
  sections: ResumeSection[];
}

// ---- API payload shapes ----
export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface DocumentInfo {
  id: number;
  filename: string;
  kind: string;
}

export interface ProfileSummary {
  id: number;
  name: string;
  contact: Contact;
  has_master_profile: boolean;
}

export interface ProfileDetail {
  id: number;
  name: string;
  contact: Contact;
  master_profile: MasterProfile;
  documents: DocumentInfo[];
  usage?: UsageInfo;
}

export interface ApplicationSummary {
  id: number;
  profile_id: number;
  status: AppStatus;
  version: number;
  template: TemplateName;
  depth: Depth;
  url: string;
  company: string | null; // null until the posting is parsed (queued/fetching/needs_paste)
  title: string | null; // null until the posting is parsed
  cost_usd: number;
  created_at: string;
  error_message?: string | null;
  stage: Stage;
  applied_at: string | null;
  archived_at: string | null;
  last_activity_at: string;
}

export interface ApplicationDetail extends ApplicationSummary {
  resume: ResumeDoc | null;
  cover_letter_md: string | null;
  tailoring_notes: string | null;
  research: ResearchFindings | null;
  parsed: ParsedPosting | null;
  raw_text_present: boolean;
  events: ApplicationEvent[];
}

export interface SettingsShape {
  api_key_set: boolean;
  fake_mode: boolean;
  default_template: TemplateName;
  default_depth: Depth;
  page_size: PageSize;
}

export interface JobRequest {
  url: string;
  depth?: Depth;
  template?: TemplateName;
}

export interface TemplateInfo {
  name: TemplateName;
  label: string;
  description: string;
  best_for: string;
}

export interface SetupShape {
  platform: "windows" | "posix";
  python_path: string;
  mcp_server_path: string;
  mcp_server_exists: boolean;
  mcp_command: string;
  env_line: string;
  workflow_guide_tool: string;
}
