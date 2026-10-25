import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard,
  FileUp,
  Sparkles,
  BookOpen,
  BarChart3,
  Award,
  LogOut,
  Menu,
  X,
  GraduationCap,
  ChevronRight,
  ShieldCheck,
  User as UserIcon,
} from 'lucide-react';

const Layout = () => {
  const { user, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const isProfessor = user?.role === 'professor';

  const professorNav = [
    { name: 'Dashboard', path: '/professor/dashboard', icon: LayoutDashboard },
    { name: 'Upload Curriculum', path: '/professor/curriculum', icon: FileUp },
    { name: 'Generate Exam', path: '/professor/generate', icon: Sparkles },
    { name: 'Exam List', path: '/professor/exams', icon: BookOpen },
    { name: 'Analytics', path: '/professor/analytics', icon: BarChart3 },
  ];

  const studentNav = [
    { name: 'Dashboard', path: '/student/dashboard', icon: LayoutDashboard },
    { name: 'Available Exams', path: '/student/exams', icon: BookOpen },
    { name: 'My Results', path: '/student/results', icon: Award },
  ];

  const navItems = isProfessor ? professorNav : studentNav;

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col md:flex-row">
      {/* Mobile Header Bar */}
      <div className="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center shadow-sm">
            <GraduationCap className="w-5 h-5" />
          </div>
          <span className="font-bold text-gray-900 text-base">EduAssess</span>
        </div>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-lg text-gray-600 hover:bg-gray-100"
          aria-label="Toggle menu"
        >
          {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Sidebar Overlay on Mobile */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar Navigation */}
      <aside
        className={`fixed md:sticky top-0 left-0 bottom-0 z-40 w-64 bg-white border-r border-gray-200/80 flex flex-col justify-between transition-transform duration-200 ease-in-out md:translate-x-0 ${
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        } h-screen`}
      >
        <div className="flex flex-col h-full">
          {/* Logo Brand Header */}
          <div className="p-5 border-b border-gray-100 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-700 to-indigo-500 text-white flex items-center justify-center shadow-md shadow-indigo-100">
              <GraduationCap className="w-6 h-6" />
            </div>
            <div>
              <h1 className="font-bold text-gray-900 text-base tracking-tight leading-snug">
                IEAS Portal
              </h1>
              <p className="text-[11px] font-medium text-indigo-600 uppercase tracking-wider">
                Assessment System
              </p>
            </div>
          </div>

          {/* User Profile Card */}
          <div className="p-4 mx-3 my-3 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-sm shrink-0">
              {user?.name ? user.name.charAt(0).toUpperCase() : 'U'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-gray-900 truncate">
                {user?.name || 'User Account'}
              </p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    isProfessor ? 'bg-indigo-500' : 'bg-emerald-500'
                  }`}
                />
                <span className="text-[11px] font-medium text-gray-500 capitalize">
                  {user?.role || 'User'}
                </span>
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 px-3 py-2 space-y-1 overflow-y-auto">
            <div className="px-3 py-1.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
              {isProfessor ? 'Instructor Menu' : 'Student Menu'}
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'text-gray-600 hover:text-indigo-600 hover:bg-indigo-50/60'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <div className="flex items-center gap-3">
                        <Icon
                          className={`w-4 h-4 ${
                            isActive ? 'text-white' : 'text-gray-400 group-hover:text-indigo-600'
                          }`}
                        />
                        <span>{item.name}</span>
                      </div>
                      {isActive && <ChevronRight className="w-4 h-4 text-white/70" />}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* System Status / Logout at bottom */}
          <div className="p-4 border-t border-gray-100">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium text-rose-600 hover:bg-rose-50 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-h-screen overflow-x-hidden">
        {/* Top Navbar */}
        <header className="hidden md:flex h-16 bg-white border-b border-gray-200/80 px-8 items-center justify-between sticky top-0 z-30 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold px-2.5 py-1 rounded-md bg-indigo-50 text-indigo-700 border border-indigo-100 flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5" />
              {isProfessor ? 'Professor Workspace' : 'Student Portal'}
            </span>
            <span className="text-gray-300">|</span>
            <span className="text-xs text-gray-500 font-medium">
              Intelligent Educational Assessment System
            </span>
          </div>

          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-xs font-semibold text-gray-900">{user?.name || 'User'}</p>
              <p className="text-[11px] text-gray-500">{user?.email || ''}</p>
            </div>
            <button
              onClick={handleLogout}
              title="Sign Out"
              className="p-2 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </header>

        {/* Page Content Body */}
        <main className="flex-1 p-4 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;
