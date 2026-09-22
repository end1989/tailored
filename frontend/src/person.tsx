// The active person: who this browser is working for.
//
// One install serves several people. The choice lives in this browser only
// (localStorage, so each Chrome profile keeps its own) and never on the
// server: an MCP agent always names its profile_id, and what it writes must
// not depend on what happens to be selected in some browser tab.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { listProfiles } from "./api";
import type { ProfileSummary } from "./types";

export const PERSON_STORAGE_KEY = "tailored-person";

/** A person's id, or "new" for the picker's "Add a person" option. */
export type SwitchTarget = number | "new";

export interface PersonContextValue {
  /** Every person, ordered by id (as GET /api/profiles returns them). */
  people: ProfileSummary[];
  /** Null while loading, after a failed first load, or with no people. */
  person: ProfileSummary | null;
  /** True until the first listProfiles() settles. */
  loading: boolean;
  /** The first load's failure; a failed later refresh keeps the last list. */
  error: string | null;
  /** One line shown under the picker. */
  notice: string | null;
  setNotice(message: string | null): void;
  /** Programmatic switch: bypasses the guard; remember defaults to true; no-op for an unknown id. */
  setPersonId(id: number, opts?: { remember?: boolean }): void;
  /** Picker switch: honours the guard. True means done now (for "new", the caller navigates). */
  requestSwitch(target: SwitchTarget): boolean;
  pendingSwitch: { target: SwitchTarget; message: string } | null;
  /** Performs the pending switch (remembered) and returns its target, or null if none. */
  confirmSwitch(): SwitchTarget | null;
  cancelSwitch(): void;
  /** Reloads the list; with selectId, switches to (and remembers) that person. Never rejects. */
  refreshPeople(selectId?: number): Promise<void>;
  /** A message while a screen holds work a switch would lose; null to clear. */
  setSwitchGuard(message: string | null): void;
  /** The name; for duplicate names "name (email)", or "name #id" without a distinct email. */
  labelFor(p: ProfileSummary): string;
}

export const PersonContext = createContext<PersonContextValue | null>(null);

/** What identifies a person across reloads. The id alone is not enough:
 * SQLite hands a removed person's id to the next person created. */
interface PersonKey {
  id: number;
  created_at: string;
}

function keyOf(p: ProfileSummary): PersonKey {
  return { id: p.id, created_at: p.created_at };
}

function findByKey(list: ProfileSummary[], key: PersonKey | null): ProfileSummary | undefined {
  if (!key) return undefined;
  return list.find((p) => p.id === key.id && p.created_at === key.created_at);
}

function readStored(): PersonKey | null {
  try {
    const raw = localStorage.getItem(PERSON_STORAGE_KEY);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const { id, created_at } = value as Record<string, unknown>;
      if (typeof id === "number" && typeof created_at === "string") return { id, created_at };
    }
  } catch {
    // Storage blocked, or a value that is not JSON: treat as nothing stored.
  }
  return null;
}

function writeStored(p: ProfileSummary): void {
  try {
    localStorage.setItem(PERSON_STORAGE_KEY, JSON.stringify(keyOf(p)));
  } catch {
    // Storage blocked: the choice lives in memory for this visit.
  }
}

/** The person's name, made distinct when someone else has the same name. */
function labelIn(p: ProfileSummary, people: ProfileSummary[]): string {
  const name = p.name.trim();
  const others = people.filter((o) => o.id !== p.id && o.name.trim() === name);
  if (others.length === 0) return p.name;
  const email = (p.contact?.email ?? "").trim();
  const emailIsShared = others.some((o) => (o.contact?.email ?? "").trim() === email);
  return email && !emailIsShared ? `${p.name} (${email})` : `${p.name} #${p.id}`;
}

export function PersonProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<ProfileSummary[]>([]);
  const [selected, setSelected] = useState<PersonKey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingSwitch, setPendingSwitch] = useState<{ target: SwitchTarget; message: string } | null>(
    null
  );

  // Mirrors of the state above, read by callbacks that must see the latest
  // values (a refresh that resolves after a switch, a setPersonId called right
  // after `await refreshPeople()`), not the ones from the render that made them.
  const peopleRef = useRef<ProfileSummary[]>([]);
  const selectedRef = useRef<PersonKey | null>(null);
  const pendingRef = useRef<{ target: SwitchTarget; message: string } | null>(null);
  const guardRef = useRef<string | null>(null);
  const loadedRef = useRef(false);
  const seqRef = useRef(0);
  const selectAfterLoadRef = useRef<number | undefined>(undefined);
  // The most recently started refreshPeople() run. A superseded call awaits
  // this (unless it IS this, which means nothing newer exists - only
  // unmount advanced seqRef - and there is nothing to wait for) so its
  // promise never resolves before the run that superseded it has applied
  // its list.
  const latestRunRef = useRef<Promise<void> | null>(null);

  const select = useCallback((p: ProfileSummary | null, remember: boolean) => {
    const key = p ? keyOf(p) : null;
    selectedRef.current = key;
    setSelected(key);
    if (p && remember) writeStored(p);
  }, []);

  const setPending = useCallback((next: { target: SwitchTarget; message: string } | null) => {
    pendingRef.current = next;
    setPendingSwitch(next);
  }, []);

  const applyList = useCallback(
    (list: ProfileSummary[], selectId: number | undefined) => {
      const previousPeople = peopleRef.current;
      const previous = findByKey(previousPeople, selectedRef.current);
      peopleRef.current = list;
      setPeople(list);

      const wanted = selectId === undefined ? undefined : list.find((p) => p.id === selectId);
      if (wanted) {
        select(wanted, true);
        return;
      }
      const still = findByKey(list, selectedRef.current);
      if (still) {
        select(still, false);
        return;
      }
      const storedPerson = findByKey(list, readStored());
      if (previous) {
        // The current person is gone (or their id now belongs to someone
        // new). Fall back to the first person. Rewrite the stored entry only
        // when it names nobody, so a person shown for one visit
        // (remember: false) does not change where this browser opens.
        setNotice(`${labelIn(previous, previousPeople)} was removed.`);
        select(list[0] ?? null, !storedPerson);
        return;
      }
      // First good load: the remembered person if they still exist, else the
      // first person, remembered from now on.
      if (storedPerson) {
        select(storedPerson, false);
        return;
      }
      select(list[0] ?? null, true);
    },
    [select]
  );

  const refreshPeople = useCallback(
    (selectId?: number): Promise<void> => {
      const seq = ++seqRef.current;
      if (selectId !== undefined) selectAfterLoadRef.current = selectId;

      let run: Promise<void>;

      // Called once this call knows it was superseded (by a newer refresh,
      // not merely by unmount - see latestRunRef's comment). Waits for the
      // call that superseded us, so our own promise settles only once the
      // list it resolves to is the one actually applied.
      const waitForNewer = async () => {
        const latest = latestRunRef.current;
        if (latest && latest !== run) await latest;
      };

      run = (async () => {
        try {
          const list = await listProfiles();
          if (seq !== seqRef.current) {
            await waitForNewer();
            return;
          }
          const want = selectAfterLoadRef.current;
          selectAfterLoadRef.current = undefined;
          loadedRef.current = true;
          setError(null);
          applyList(list, want);
        } catch (e) {
          if (seq !== seqRef.current) {
            await waitForNewer();
            return;
          }
          // This call owns whatever selectId is currently pending (nothing
          // newer has claimed it): a switch that failed must not be granted
          // later by some unrelated refresh that happens to succeed.
          selectAfterLoadRef.current = undefined;
          // After a good load, a failed refresh keeps the last list and person
          // rather than blanking every screen over a blip.
          if (!loadedRef.current) setError(e instanceof Error ? e.message : String(e));
        } finally {
          if (seq === seqRef.current) setLoading(false);
        }
      })();

      latestRunRef.current = run;
      return run;
    },
    [applyList]
  );

  useEffect(() => {
    void refreshPeople();
    return () => {
      // Drop whatever is still in flight: it belongs to an unmounted provider.
      seqRef.current += 1;
    };
  }, [refreshPeople]);

  useEffect(() => {
    function onVisibility() {
      if (document.visibilityState === "visible") void refreshPeople();
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [refreshPeople]);

  const setPersonId = useCallback(
    (id: number, opts?: { remember?: boolean }) => {
      const target = peopleRef.current.find((p) => p.id === id);
      if (!target) return;
      select(target, opts?.remember ?? true);
    },
    [select]
  );

  const switchNow = useCallback(
    (target: SwitchTarget) => {
      setNotice(null);
      if (target !== "new") setPersonId(target, { remember: true });
    },
    [setPersonId]
  );

  const requestSwitch = useCallback(
    (target: SwitchTarget): boolean => {
      if (target !== "new" && target === selectedRef.current?.id) {
        setPending(null);
        return true;
      }
      const guard = guardRef.current;
      if (guard) {
        setPending({ target, message: guard });
        return false;
      }
      setPending(null);
      switchNow(target);
      return true;
    },
    [setPending, switchNow]
  );

  const confirmSwitch = useCallback((): SwitchTarget | null => {
    const pending = pendingRef.current;
    setPending(null);
    if (!pending) return null;
    switchNow(pending.target);
    return pending.target;
  }, [setPending, switchNow]);

  const cancelSwitch = useCallback(() => setPending(null), [setPending]);

  const setSwitchGuard = useCallback((message: string | null) => {
    guardRef.current = message;
  }, []);

  const person = useMemo(() => findByKey(people, selected) ?? null, [people, selected]);
  const labelFor = useCallback((p: ProfileSummary) => labelIn(p, people), [people]);

  const value = useMemo<PersonContextValue>(
    () => ({
      people,
      person,
      loading,
      error,
      notice,
      setNotice,
      setPersonId,
      requestSwitch,
      pendingSwitch,
      confirmSwitch,
      cancelSwitch,
      refreshPeople,
      setSwitchGuard,
      labelFor,
    }),
    [
      people,
      person,
      loading,
      error,
      notice,
      setPersonId,
      requestSwitch,
      pendingSwitch,
      confirmSwitch,
      cancelSwitch,
      refreshPeople,
      setSwitchGuard,
      labelFor,
    ]
  );

  return <PersonContext.Provider value={value}>{children}</PersonContext.Provider>;
}

export function usePerson(): PersonContextValue {
  const ctx = useContext(PersonContext);
  if (!ctx) throw new Error("usePerson must be used inside <PersonProvider>");
  return ctx;
}
