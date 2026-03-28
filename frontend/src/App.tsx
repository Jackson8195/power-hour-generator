import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import ProjectPage from "./pages/ProjectPage";
import LandingPage from "./pages/LandingPage";
import MixtapeBinderPage from "./pages/MixtapeBinderPage";
import AutoGeneratePage from "./pages/AutoGeneratePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Full-screen retro pages — no Layout wrapper */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/mixtapes" element={<MixtapeBinderPage />} />
        <Route path="/auto-generate" element={<AutoGeneratePage />} />

        {/* Layout-wrapped routes */}
        <Route element={<Layout />}>
          <Route path="/create" element={<HomePage />} />
          <Route path="/project/:id" element={<ProjectPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
