import type { ChangeEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePerson } from "../person";
import type { SwitchTarget } from "../person";

/** Where "Add a person" goes: the Profiles screen's create form. */
const NEW_PERSON_PATH = "/profiles?new=1";

// The one ellipsis character the voice rules allow: the spec writes it this way.
const ADD_A_PERSON_OPTION = "Add a person…";

/**
 * The app-wide person switch in the nav. The select is controlled by the
 * provider's person, so after any pick it shows whoever is actually selected:
 * the "Add a person" option can be picked again, and a switch the guard held
 * back shows the unchanged person.
 */
export default function PersonPicker() {
  const {
    people,
    person,
    loading,
    error,
    notice,
    setNotice,
    requestSwitch,
    pendingSwitch,
    confirmSwitch,
    cancelSwitch,
    labelFor,
  } = usePerson();
  const navigate = useNavigate();
  const location = useLocation();

  function afterSwitch(target: SwitchTarget) {
    if (target === "new") {
      navigate(NEW_PERSON_PATH);
    } else if (location.pathname.startsWith("/applications/")) {
      // The open application belongs to the previous person.
      navigate("/");
    }
  }

  function onChange(e: ChangeEvent<HTMLSelectElement>) {
    const target: SwitchTarget = e.target.value === "new" ? "new" : Number(e.target.value);
    if (requestSwitch(target)) afterSwitch(target);
  }

  function onConfirm() {
    const target = confirmSwitch();
    if (target !== null) afterSwitch(target);
  }

  const noPeople = !loading && !error && people.length === 0;

  return (
    <div className="person-picker">
      {person ? (
        <select
          className="select person-select"
          aria-label="Person"
          value={person.id}
          onChange={onChange}
        >
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {labelFor(p)}
            </option>
          ))}
          <option value="new">{ADD_A_PERSON_OPTION}</option>
        </select>
      ) : noPeople ? (
        <Link to={NEW_PERSON_PATH} className="nav-link">
          Add a person
        </Link>
      ) : null}
      {person?.inbox_url ? (
        <a
          href={person.inbox_url}
          target="_blank"
          rel="noopener noreferrer"
          className="nav-link"
        >
          Inbox
        </a>
      ) : null}
      {pendingSwitch || notice ? (
        <div className="person-popovers">
          {pendingSwitch ? (
            <div role="alert" className="person-popover">
              <span className="person-popover-message">{pendingSwitch.message}</span>
              <button type="button" className="btn btn-small btn-danger" onClick={onConfirm}>
                Switch anyway
              </button>
              <button type="button" className="btn btn-small btn-primary" onClick={cancelSwitch}>
                Stay
              </button>
            </div>
          ) : null}
          {notice ? (
            <div role="status" className="person-popover">
              <span className="person-popover-message">{notice}</span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label="Dismiss"
                onClick={() => setNotice(null)}
              >
                ×
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
