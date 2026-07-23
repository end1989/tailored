import { NavLink, Route, Routes } from "react-router-dom";
import DashboardScreen from "./screens/DashboardScreen";
import AddJobsScreen from "./screens/AddJobsScreen";
import TemplatesScreen from "./screens/TemplatesScreen";
import ProfileScreen from "./screens/ProfileScreen";
import ApplicationScreen from "./screens/ApplicationScreen";
import SettingsScreen from "./screens/SettingsScreen";

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
          <NavLink to="/templates" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Templates
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
          <Route path="/" element={<DashboardScreen />} />
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
