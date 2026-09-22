import { useEffect, useState } from "react";
import { getSetup } from "../api";
import { usePerson } from "../person";
import type { SetupShape } from "../types";
import CopyButton from "./CopyButton";

const GUIDE_STEP = "Read Tailored's workflow guide (the get_workflow_guide tool), then ";

const URL_LIST = "<paste your job URLs, one per line>";

const MANUAL_COMMAND =
  'claude mcp add tailored -- "<path to your Python>" "<path to>/backend/mcp_server.py"';

// With several people, get_master_profile() without an id errors, so the
// prompts carry the person's id. The name (not the picker label) is used:
// the id already tells two people with one name apart.
type PromptPerson = { id: number; name: string } | null;

function agentPrompt(p: PromptPerson): string {
  return p
    ? `${GUIDE_STEP}tailor a resume and cover letter for ${p.name} (profile_id ${p.id}) from <job url>.`
    : `${GUIDE_STEP}tailor my profile for <job url>.`;
}

function batchPrompt(p: PromptPerson): string {
  const whom = p ? `${p.name} (profile_id ${p.id})` : "my profile";
  return `${GUIDE_STEP}queue these jobs for ${whom} and work through them one at a time:\n${URL_LIST}`;
}

export default function McpSetup() {
  const { person, loading } = usePerson();
  const [setup, setSetup] = useState<SetupShape | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getSetup()
      .then(setSetup)
      .catch(() => setFailed(true));
  }, []);

  const command = setup?.mcp_command ?? MANUAL_COMMAND;
  const agent = agentPrompt(person);
  const batch = batchPrompt(person);

  return (
    <div className="mcp-setup">
      <p className="muted">
        Register Tailored with Claude Code (or any MCP-capable agent). This path assumes you
        already have such an agent installed.
      </p>
      {failed && (
        <p className="muted">
          Couldn't detect your paths automatically — fill in the two paths in the command below.
        </p>
      )}
      {setup && !setup.mcp_server_exists && (
        <div className="alert alert-error">
          Expected the MCP server at <span className="mono">{setup.mcp_server_path}</span> but
          couldn't find it — is your clone complete?
        </div>
      )}
      <div className="field">
        <label className="field-label">1. Register the MCP server</label>
        <pre className="code-block mono">{command}</pre>
        <CopyButton text={command} label="Copy command" />
      </div>
      {/* The prompts name the person, so they wait for the person list. */}
      {!loading && (
        <>
          <div className="field">
            <label className="field-label">2. Ask your agent</label>
            <pre className="code-block mono">{agent}</pre>
            <CopyButton text={agent} label="Copy prompt" />
          </div>
          <div className="field">
            <label className="field-label">Or hand it a whole list</label>
            <pre className="code-block mono">{batch}</pre>
            <CopyButton text={batch} label="Copy batch prompt" />
            <p className="muted">
              Queueing is free and instant: every URL appears on your dashboard as a
              saved job right away, and the agent works through them one at a time. The
              queue lives in the database, so if the agent restarts it resumes where it
              stopped instead of starting over.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
