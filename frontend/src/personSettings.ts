import { useEffect, useRef, useState } from "react";
import { getSettings, updateSettings } from "./api";
import { usePerson } from "./person";
import type { Depth, PageSize, SettingsShape, TemplateName } from "./types";

export interface SettingsPatch {
  default_template?: TemplateName;
  default_depth?: Depth;
  page_size?: PageSize;
}

// Whose settings are being edited: a person's id, null for the app-wide
// defaults (only when there are no people), or undefined while that is not
// known (the person list is loading or failed to load).
type Target = number | null | undefined;

interface Loaded {
  target: number | null;
  settings: SettingsShape | null;
  error: string | null;
}

export interface PersonSettings {
  /** The current person's effective settings; null until they arrive, and again right after a switch. */
  settings: SettingsShape | null;
  /** The person-list error, or a failed read or write for the current person. */
  error: string | null;
  /** Writes a change for whoever is current at the moment of the call. Never throws. */
  save(patch: SettingsPatch): Promise<void>;
}

/**
 * The settings the Settings and Templates screens edit: the current person's
 * own values when there is a person, the app-wide defaults when there are no
 * people. Nothing is requested while the person list is loading or failed.
 * A read or write that settles after the person changed is dropped, so one
 * person's values are never shown, or saved back, under another person's name.
 */
export function usePersonSettings(): PersonSettings {
  const { person, loading, error: peopleError } = usePerson();
  const target: Target = loading || peopleError ? undefined : person ? person.id : null;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const targetRef = useRef<Target>(target);
  targetRef.current = target;

  useEffect(() => {
    if (target === undefined) return;
    let alive = true;
    getSettings(target ?? undefined)
      .then((s) => {
        if (alive) setLoaded({ target, settings: s, error: null });
      })
      .catch((e) => {
        if (alive) setLoaded({ target, settings: null, error: String(e) });
      });
    return () => {
      alive = false;
    };
  }, [target]);

  async function save(patch: SettingsPatch): Promise<void> {
    const at = targetRef.current;
    if (at === undefined) return;
    setLoaded((prev) => (prev && prev.target === at ? { ...prev, error: null } : prev));
    try {
      const s = await updateSettings(patch, at ?? undefined);
      if (targetRef.current !== at) return;
      setLoaded({ target: at, settings: s, error: null });
    } catch (err) {
      if (targetRef.current !== at) return;
      setLoaded((prev) =>
        prev && prev.target === at
          ? { ...prev, error: String(err) }
          : { target: at, settings: null, error: String(err) }
      );
    }
  }

  const mine = target !== undefined && loaded?.target === target ? loaded : null;
  return {
    settings: mine?.settings ?? null,
    error: peopleError ?? mine?.error ?? null,
    save,
  };
}
