import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Shell } from './Shell';
import { Overview } from './pages/Overview';
import { Datasets } from './pages/Datasets';
import { Dataset } from './pages/Dataset';
import { Queries } from './pages/Queries';
import { Query } from './pages/Query';
import { Validators } from './pages/Validators';
import { Leaderboard } from './pages/Leaderboard';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Overview />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/datasets/:key" element={<Dataset />} />
          <Route path="/queries" element={<Queries />} />
          <Route path="/queries/:key/:n" element={<Query />} />
          <Route path="/validators" element={<Validators />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
