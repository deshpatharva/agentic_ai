import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import './index.css';

import ProtectedRoute from './components/ProtectedRoute';
import GuestRoute from './components/GuestRoute';
import AdminRoute from './components/AdminRoute';
import RequireProfile from './components/RequireProfile';

// Route-level code splitting: each page loads on demand, keeping the
// landing 3D bundle and admin charts out of the initial chunk.
const Landing          = lazy(() => import('./pages/Landing'));
const Login            = lazy(() => import('./pages/Login'));
const Register         = lazy(() => import('./pages/Register'));
const Dashboard        = lazy(() => import('./pages/Dashboard'));
const JobMatches       = lazy(() => import('./pages/JobMatches'));
const Settings         = lazy(() => import('./pages/Settings'));
const Resumes          = lazy(() => import('./pages/Resumes'));
const ProfilesPage     = lazy(() => import('./pages/ProfilesPage'));
const ProfileNewPage   = lazy(() => import('./pages/ProfileNewPage'));
const ChatOptimizePage = lazy(() => import('./pages/ChatOptimizePage'));
const NotFound         = lazy(() => import('./pages/NotFound'));
const AdminLayout      = lazy(() => import('./pages/admin/AdminLayout'));
const AdminDashboard   = lazy(() => import('./pages/admin/AdminDashboard'));
const PipelineRuns     = lazy(() => import('./pages/admin/PipelineRuns'));
const Observability    = lazy(() => import('./pages/admin/Observability'));
const UserList         = lazy(() => import('./pages/admin/UserList'));
const UserDetail       = lazy(() => import('./pages/admin/UserDetail'));
const AdminAnalytics   = lazy(() => import('./pages/admin/Analytics'));
const PromoCodes       = lazy(() => import('./pages/admin/PromoCodes'));

function PageFallback() {
  return (
    <div className="min-h-screen bg-surface flex items-center justify-center">
      <span className="text-ink-faint text-sm">Loading…</span>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            borderRadius: '8px',
            fontFamily: 'Inter, sans-serif',
            background: 'rgb(var(--c-surface))',
            color: 'rgb(var(--c-ink))',
            border: '1px solid rgb(var(--c-line))',
          },
        }}
      />
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/"         element={<Landing />} />
          <Route path="/login"    element={<GuestRoute><Login /></GuestRoute>} />
          <Route path="/register" element={<GuestRoute><Register /></GuestRoute>} />
          <Route path="/app"      element={<Navigate to="/optimize" />} />
          <Route path="/optimize" element={<ProtectedRoute><RequireProfile><ChatOptimizePage /></RequireProfile></ProtectedRoute>} />

          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/dashboard/matches"  element={<ProtectedRoute><JobMatches /></ProtectedRoute>} />
          <Route path="/dashboard/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
          <Route path="/dashboard/resumes"  element={<ProtectedRoute><Resumes /></ProtectedRoute>} />
          <Route path="/profiles"     element={<ProtectedRoute><ProfilesPage /></ProtectedRoute>} />
          <Route path="/profiles/new" element={<ProtectedRoute><ProfileNewPage /></ProtectedRoute>} />

          <Route
            path="/admin"
            element={<AdminRoute><AdminLayout /></AdminRoute>}
          >
            <Route index element={<AdminDashboard />} />
            <Route path="runs" element={<PipelineRuns />} />
            <Route path="users" element={<UserList />} />
            <Route path="users/:id" element={<UserDetail />} />
            <Route path="promo-codes" element={<PromoCodes />} />
            <Route path="analytics" element={<AdminAnalytics />} />
            <Route path="observability" element={<Observability />} />
          </Route>

          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
