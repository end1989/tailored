import { useEffect, useRef, useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
}

export default function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const resetTimer = useRef<number | undefined>(undefined);

  // A pending reset must not outlive the button: firing after unmount would
  // schedule a state update on a component that no longer exists.
  useEffect(() => {
    return () => {
      if (resetTimer.current !== undefined) {
        window.clearTimeout(resetTimer.current);
      }
    };
  }, []);

  async function handleCopy() {
    // Both flags reset up front. "Copied!" wins in the render below, so a
    // failure landing inside the previous copy's 1.5s success window would
    // otherwise keep claiming success for a copy that did not happen.
    setCopied(false);
    setFailed(false);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      // Drop the earlier click's reset before scheduling this one; its older
      // deadline would blank the label moments after this copy succeeded.
      if (resetTimer.current !== undefined) {
        window.clearTimeout(resetTimer.current);
      }
      resetTimer.current = window.setTimeout(() => setCopied(false), 1500);
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
