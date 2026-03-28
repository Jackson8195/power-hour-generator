import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import ProjectPage from "./pages/ProjectPage";
import LandingPage from "./pages/LandingPage";
import MixtapeBinderPage from "./pages/MixtapeBinderPage";
import AutoGeneratePage from "./pages/AutoGeneratePage";
import AutoGenerateProgressPage from "./pages/AutoGenerateProgressPage";
import WorksInProgressPage from "./pages/WorksInProgressPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Full-screen retro pages — no Layout wrapper */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/mixtapes" element={<MixtapeBinderPage />} />
        <Route path="/auto-generate" element={<AutoGeneratePage />} />
        <Route path="/auto-generate/progress/:jobId" element={<AutoGenerateProgressPage />} />

        {/* Layout-wrapped routes */}
        <Route element={<Layout />}>
          <Route path="/create" element={<HomePage />} />
          <Route path="/works-in-progress" element={<WorksInProgressPage />} />
          <Route path="/project/:id" element={<ProjectPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
