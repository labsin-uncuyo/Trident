import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { TopologyPage } from './pages/TopologyPage';
import { AgentsPage } from './pages/AgentsPage';
import { SessionDetailPage } from './pages/SessionDetailPage';
import { AlertsPage } from './pages/AlertsPage';
import { TrafficPage } from './pages/TrafficPage';
import { RunsPage } from './pages/RunsPage';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<TopologyPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:host/:sessionId" element={<SessionDetailPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="traffic" element={<TrafficPage />} />
          <Route path="runs" element={<RunsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
