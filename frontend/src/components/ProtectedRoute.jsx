import React from 'react';
import { Navigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from './ui/LoadingSpinner';
import { ShieldAlert, ArrowLeft } from 'lucide-react';

const ProtectedRoute = ({ children, role }) => {
  const { user, isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cream">
        <LoadingSpinner size="lg" message="بنتحقق من صلاحياتك..." />
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (role && user.role !== role) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cream px-4">
        <div className="max-w-md w-full bg-paper p-8 rounded-2xl shadow-warm border border-cocoa-300/40 text-center">
          <div className="w-16 h-16 bg-rose-50 text-rose-600 rounded-2xl rounded-br-md flex items-center justify-center mx-auto mb-4 -rotate-3">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h2 className="text-2xl font-extrabold text-ink mb-2">مش مسموح (403)</h2>
          <p className="text-cocoa-500 text-sm mb-6 leading-relaxed">
            معندكش صلاحية تدخل الصفحة دي — دي مخصوصة لحسابات{' '}
            <span className="font-bold text-cocoa-800">
              {role === 'professor' ? 'الأستاذ' : 'الطالب'}
            </span>
            ، وإنت مسجّل بحساب{' '}
            <span className="font-bold text-cocoa-800">
              {user.role === 'professor' ? 'أستاذ' : user.role === 'student' ? 'طالب' : user.role || 'غير معروف'}
            </span>
            .
          </p>
          <div className="flex flex-col gap-2">
            <Link
              to={user.role === 'professor' ? '/professor/dashboard' : '/student/dashboard'}
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-b from-clay-600 to-clay-800 hover:from-clay-500 text-white rounded-xl text-sm font-bold transition-colors shadow-warm btn-cut"
            >
              <ArrowLeft className="w-4 h-4" />
              ارجع للوحتي
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return children;
};

export default ProtectedRoute;
