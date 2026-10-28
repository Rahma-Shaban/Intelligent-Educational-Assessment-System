import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import ChatBot from './ChatBot';
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
  ChevronLeft,
  User as UserIcon,
} from 'lucide-react';

export const BrandMark = ({ size = 'md' }) => {
  const dims =
    size === 'lg'
      ? 'w-12 h-12 text-xl rounded-2xl'
      : size === 'sm'
      ? 'w-8 h-8 text-xs rounded-lg'
      : 'w-10 h-10 text-base rounded-xl';
  return (
    <div
      className={`${dims} bg-gradient-to-br from-gold-400 to-gold-500 text-clay-950 font-code font-bold flex items-center justify-center shadow-warm -rotate-3 select-none shrink-0`}
    >
      &lt;/&gt;
    </div>
  );
};

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
    { name: 'الرئيسية', path: '/professor/dashboard', icon: LayoutDashboard },
    { name: 'رفع المنهج', path: '/professor/curriculum', icon: FileUp },
    { name: 'إنشاء امتحان', path: '/professor/generate', icon: Sparkles },
    { name: 'قائمة الامتحانات', path: '/professor/exams', icon: BookOpen },
    { name: 'الإحصائيات', path: '/professor/analytics', icon: BarChart3 },
  ];

  const studentNav = [
    { name: 'الرئيسية', path: '/student/dashboard', icon: LayoutDashboard },
    { name: 'الامتحانات المتاحة', path: '/student/exams', icon: BookOpen },
    { name: 'نتائجي', path: '/student/results', icon: Award },
  ];

  const navItems = isProfessor ? professorNav : studentNav;

  return (
    <div className="min-h-screen bg-cream flex flex-col md:flex-row">
      {/* Mobile Header Bar */}
      <div className="md:hidden bg-cocoa-950 border-b border-white/10 px-4 py-3 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center gap-2.5">
          <BrandMark size="sm" />
          <span className="font-display text-gold-400 text-lg leading-none pt-1">IAS</span>
        </div>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-lg text-cocoa-300 hover:bg-white/10"
          aria-label="القائمة"
        >
          {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Sidebar Overlay on Mobile */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 bg-cocoa-950/60 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar Navigation — RTL: anchored to the right */}
      <aside
        className={`fixed md:sticky top-0 right-0 bottom-0 z-40 w-64 bg-cocoa-950 border-e border-white/10 flex flex-col justify-between transition-transform duration-200 ease-in-out md:translate-x-0 ${
          mobileMenuOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
        } h-screen`}
      >
        <div className="flex flex-col h-full">
          {/* Logo Brand Header */}
          <div className="p-5 border-b border-white/10 flex items-center gap-3">
            <BrandMark />
            <div>
              <h1 className="font-display text-2xl text-gold-400 leading-none pt-1">
                IA<span className="text-white">S</span>
              </h1>
              <p className="text-[11px] font-semibold text-cocoa-300 mt-0.5">
                منصة التقييم الذكية
              </p>
            </div>
          </div>

          {/* User Profile Card */}
          <div className="p-4 mx-3 my-3 bg-white/5 border border-white/10 rounded-2xl flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl rounded-br-sm bg-teal-700 text-white flex items-center justify-center font-bold text-sm shrink-0">
              {user?.name ? user.name.charAt(0).toUpperCase() : 'U'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold text-white truncate">
                {user?.name || 'حساب المستخدم'}
              </p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    isProfessor ? 'bg-gold-400' : 'bg-teal-500'
                  }`}
                />
                <span className="text-[11px] font-medium text-cocoa-300">
                  {isProfessor ? 'أستاذ' : 'طالب'}
                </span>
              </div>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 px-3 py-2 space-y-1 overflow-y-auto">
            <div className="px-3 py-1.5 text-[11px] font-bold text-cocoa-500 tracking-wide">
              {isProfessor ? 'مساحة الأستاذ' : 'بوابة الطالب'}
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-bold transition-all ${
                      isActive
                        ? 'bg-gradient-to-l from-clay-700 to-clay-800 text-white shadow-pop'
                        : 'text-cocoa-300 hover:text-gold-300 hover:bg-white/5'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <div className="flex items-center gap-3">
                        <Icon
                          className={`w-4 h-4 ${
                            isActive ? 'text-gold-300' : 'text-cocoa-500'
                          }`}
                        />
                        <span>{item.name}</span>
                      </div>
                      {isActive && <ChevronLeft className="w-4 h-4 text-gold-300/70" />}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Logout at bottom */}
          <div className="p-4 border-t border-white/10">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-bold text-rose-300 hover:bg-rose-500/10 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span>تسجيل الخروج</span>
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-h-screen overflow-x-hidden">
        {/* Top Navbar */}
        <header className="hidden md:flex h-16 bg-paper border-b border-sand px-8 items-center justify-between sticky top-0 z-30 shadow-[0_1px_3px_rgba(74,35,16,0.06)]">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold px-2.5 py-1 rounded-lg bg-clay-100 text-clay-700 border border-clay-200 flex items-center gap-1.5">
              <UserIcon className="w-3.5 h-3.5" />
              {isProfessor ? 'مساحة الأستاذ' : 'بوابة الطالب'}
            </span>
            <span className="text-cocoa-300">|</span>
            <span className="text-xs text-cocoa-500 font-semibold">
              منصة التقييم التعليمي الذكية — بكالوريا البرمجة
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-left">
              <p className="text-xs font-bold text-ink">{user?.name || 'مستخدم'}</p>
              <p className="text-[11px] text-cocoa-500 font-code" dir="ltr">
                {user?.email || ''}
              </p>
            </div>
            <button
              onClick={handleLogout}
              title="تسجيل الخروج"
              className="p-2 text-cocoa-300 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </header>

        {/* Page Content Body */}
        <main className="flex-1 p-4 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>

        {/* Floating Chatbot for Students */}
        <ChatBot />
      </div>
    </div>
  );
};

export default Layout;
