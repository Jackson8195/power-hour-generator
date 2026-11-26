import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { ConfirmProvider } from "./components/ConfirmDialog";
import HomePage from "./pages/HomePage";
import ProjectPage from "./pages/ProjectPage";
import LandingPage from "./pages/LandingPage";
import TapeShelfPage from "./pages/TapeShelfPage";
import AutoGeneratePage from "./pages/AutoGeneratePage";
import AutoGenerateProgressPage from "./pages/AutoGenerateProgressPage";
import WorksInProgressPage from "./pages/WorksInProgressPage";

export default function App() {
  return (
    <BrowserRouter>
      <ConfirmProvider>
        <Routes>
          {/* The landing menu is the only full-screen page; everything else gets the nav bar. */}
          <Route path="/" element={<LandingPage />} />

          <Route element={<Layout />}>
            <Route path="/create" element={<HomePage />} />
            <Route path="/works-in-progress" element={<WorksInProgressPage />} />
            <Route path="/project/:id" element={<ProjectPage />} />
            <Route path="/power-hours" element={<TapeShelfPage />} />
            <Route path="/auto-generate" element={<AutoGeneratePage />} />
            <Route path="/auto-generate/progress/:jobId" element={<AutoGenerateProgressPage />} />
          </Route>
        </Routes>
      </ConfirmProvider>
    </BrowserRouter>
  );
}
