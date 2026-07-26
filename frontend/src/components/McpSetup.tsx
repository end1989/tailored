import { useEffect, useState } from "react";
import { getSetup } from "../api";
import type { SetupShape } from "../types";
import CopyButton from "./CopyButton";

const AGENT_PROMPT =
  "Read Tailored's workflow guide (the get_workflow_guide tool), then tailor my profile for <job url>.";

const MANUAL_COMMAND =
  'claude mcp add tailored -- "<path to your Python>" "<path to>/backend/mcp_server.py"';

export default function McpSetup() {
  const [setup, setSetup] = useState<SetupShape | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getSetup()
      .then(setSetup)
      .catch(() => setFailed(true));
  }, []);

  const command = setup?.mcp_command ?? MANUAL_COMMAND;

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
      <div className="field">
        <label className="field-label">2. Ask your agent</label>
        <pre className="code-block mono">{AGENT_PROMPT}</pre>
        <CopyButton text={AGENT_PROMPT} label="Copy prompt" />
      </div>
    </div>
  );
}
