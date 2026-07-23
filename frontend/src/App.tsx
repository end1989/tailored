import { NavLink, Route, Routes } from "react-router-dom";

// Placeholder screens — replaced by real imports in Task 17.
export function DashboardPlaceholder() {
  return <h1>Dashboard</h1>;
}
export function AddJobsPlaceholder() {
  return <h1>Add Jobs</h1>;
}
export function ProfilesPlaceholder() {
  return <h1>Profiles</h1>;
}
export function ApplicationPlaceholder() {
  return <h1>Application</h1>;
}
export function SettingsPlaceholder() {
  return <h1>Settings</h1>;
}

export default function App() {
  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <NavLink to="/" className="nav-brand">
            Tailored
          </NavLink>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Dashboard
          </NavLink>
          <NavLink to="/add" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Add Jobs
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Profiles
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Settings
          </NavLink>
        </div>
      </nav>
      <main className="shell">
        <Routes>
          <Route path="/" element={<DashboardPlaceholder />} />
          <Route path="/add" element={<AddJobsPlaceholder />} />
          <Route path="/profiles" element={<ProfilesPlaceholder />} />
          <Route path="/applications/:id" element={<ApplicationPlaceholder />} />
          <Route path="/settings" element={<SettingsPlaceholder />} />
        </Routes>
      </main>
    </>
  );
}
