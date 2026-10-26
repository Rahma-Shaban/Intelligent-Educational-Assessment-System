import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import LoadingSpinner from './components/ui/LoadingSpinner';

// Auth pages
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';

// Professor pages
import ProfessorDashboard from './pages/professor/Dashboard';
import UploadCurriculum from './pages/professor/UploadCurriculum';
import GenerateExam from './pages/professor/GenerateExam';
import ExamList from './pages/professor/ExamList';
import ExamDetail from './pages/professor/ExamDetail';
import Analytics from './pages/professor/Analytics';

// Student pages
import StudentDashboard from './pages/student/Dashboard';
import StudentExamList from './pages/student/ExamList';
import TakeExam from './pages/student/TakeExam';
import AttemptResult from './pages/student/AttemptResult';
import ResultsHistory from './pages/student/ResultsHistory';

// Redirect root based on user authentication and role
const HomeRedirect = () => {
  const { user, isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <LoadingSpinner size="lg" message="Loading application..." />
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  if (user.role === 'professor') {
    return <Navigate to="/professor/dashboard" replace />;
  }

  return <Navigate to="/student/dashboard" replace />;
};

function App() {
  return (
    <AuthProvider>
      <ErrorBoundary>
        <Routes>
          {/* Public Auth Routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* Professor Routes (Protected: role = 'professor') */}
          <Route
            path="/professor"
            element={
              <ProtectedRoute role="professor">
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<ProfessorDashboard />} />
            <Route path="curriculum" element={<UploadCurriculum />} />
            <Route path="generate" element={<GenerateExam />} />
            <Route path="exams" element={<ExamList />} />
            <Route path="exams/:id" element={<ExamDetail />} />
            <Route path="analytics" element={<Analytics />} />
          </Route>

          {/* Student Routes (Protected: role = 'student') */}
          <Route
            path="/student"
            element={
              <ProtectedRoute role="student">
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<StudentDashboard />} />
            <Route path="exams" element={<StudentExamList />} />
            <Route path="exam/:id" element={<TakeExam />} />
            <Route path="attempt/:id" element={<AttemptResult />} />
            <Route path="results" element={<ResultsHistory />} />
          </Route>

          {/* Root and Fallback Routes */}
          <Route path="/" element={<HomeRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AuthProvider>
  );
}

export default App;
