import { useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
}

export default function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function handleCopy() {
    setFailed(false);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setFailed(true);
    }
  }

  return (
    <button type="button" className="btn btn-ghost" onClick={handleCopy}>
      {copied ? "Copied!" : failed ? "Copy failed — select manually" : label}
    </button>
  );
}
