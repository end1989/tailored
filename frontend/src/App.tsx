import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import DashboardScreen from "./screens/DashboardScreen";
import GettingStartedScreen from "./screens/GettingStartedScreen";
import AddJobsScreen from "./screens/AddJobsScreen";
import TemplatesScreen from "./screens/TemplatesScreen";
import ProfileScreen from "./screens/ProfileScreen";
import ApplicationScreen from "./screens/ApplicationScreen";
import SettingsScreen from "./screens/SettingsScreen";
import { getThemePref, resolveTheme, setThemePref, subscribeTheme } from "./theme";
import type { ResolvedTheme } from "./theme";

export default function App() {
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveTheme(getThemePref())
  );

  useEffect(() => subscribeTheme((_pref, nextResolved) => setResolved(nextResolved)), []);

  function toggleTheme() {
    const next: ResolvedTheme = resolved === "dark" ? "light" : "dark";
    setThemePref(next);
  }

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
          <NavLink to="/getting-started" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Getting Started
          </NavLink>
          <NavLink to="/add" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Add Jobs
          </NavLink>
          <NavLink to="/templates" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Templates
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Profiles
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Settings
          </NavLink>
          <button
            type="button"
            className="btn btn-ghost nav-theme-toggle"
            onClick={toggleTheme}
            aria-label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {resolved === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </nav>
      <main className="shell">
        <Routes>
          <Route path="/" element={<DashboardScreen />} />
          <Route path="/getting-started" element={<GettingStartedScreen />} />
          <Route path="/add" element={<AddJobsScreen />} />
          <Route path="/templates" element={<TemplatesScreen />} />
          <Route path="/profiles" element={<ProfileScreen />} />
          <Route path="/applications/:id" element={<ApplicationScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
        </Routes>
      </main>
    </>
  );
}
