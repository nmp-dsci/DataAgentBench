import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Shell } from './Shell';
import { Overview } from './pages/Overview';
import { Datasets } from './pages/Datasets';
import { Dataset } from './pages/Dataset';
import { Query } from './pages/Query';
import { Validators } from './pages/Validators';
import { Leaderboard } from './pages/Leaderboard';
import { Runs } from './pages/Runs';
import { Run } from './pages/Run';
import { TracePage } from './pages/TracePage';
import { Agent } from './pages/Agent';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Overview />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/datasets/:key" element={<Dataset />} />
          {/* the Queries tab merged into Datasets; old links and bookmarks still land */}
          <Route path="/queries" element={<Navigate to="/datasets" replace />} />
          <Route path="/queries/:key/:n" element={<Query />} />
          <Route path="/validators" element={<Validators />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Run />} />
          <Route path="/runs/:id/traces/:key" element={<TracePage />} />
          <Route path="/agent" element={<Agent />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
