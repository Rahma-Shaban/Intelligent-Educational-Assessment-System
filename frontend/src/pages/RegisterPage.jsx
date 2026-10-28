import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Button from '../components/ui/Button';
import Alert from '../components/ui/Alert';
import { Mail, Lock, User, UserPlus, GraduationCap, BookOpen } from 'lucide-react';
import { BrandMark } from '../components/Layout';

const RegisterPage = () => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('student');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('كلمة المرور لازم تكون ٦ حروف على الأقل.');
      return;
    }

    setLoading(true);

    try {
      const user = await register(name, email, password, role);
      if (user?.role === 'professor') {
        navigate('/professor/dashboard', { replace: true });
      } else {
        navigate('/student/dashboard', { replace: true });
      }
    } catch (err) {
      console.error('Registration error:', err);
      const msg =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'حصلت مشكلة في التسجيل، راجع بياناتك وحاول مجددا.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream flex flex-col lg:flex-row">
      {/* Branded art panel */}
      <div className="relative lg:w-[42%] bg-gradient-to-bl from-teal-700 via-teal-800 to-cocoa-950 text-white px-8 py-10 lg:px-12 lg:py-12 flex flex-col overflow-hidden">
        <div className="absolute -top-20 -start-20 w-64 h-64 rounded-full bg-teal-500/20 blur-3xl" />
        <span className="code-chip-light absolute top-28 end-8 rotate-2 hidden md:inline-block">import ias</span>

        <div className="flex items-center gap-3 relative z-10">
          <BrandMark size="lg" />
          <div>
            <h2 className="font-display text-3xl leading-none pt-1">
              IA<span className="text-gold-300">S</span>
            </h2>
            <p className="text-[12px] font-semibold text-teal-100 mt-1">منصة التقييم التعليمي الذكية</p>
          </div>
        </div>

        <div className="relative z-10 mt-10 lg:mt-auto mb-8">
          <h1 className="font-display text-4xl leading-snug">
            انضم لمنصتنا
            <br />
            <span className="text-gold-300">وابدأ رحلتك 🚀</span>
          </h1>
          <ul className="mt-6 space-y-3 text-sm text-teal-100">
            <li className="flex items-center gap-2.5">
              <GraduationCap className="w-4.5 h-4.5 text-gold-300 shrink-0" />
              الأستاذ: يرفع المنهج ويولّد امتحانات ذكية
            </li>
            <li className="flex items-center gap-2.5">
              <BookOpen className="w-4.5 h-4.5 text-gold-300 shrink-0" />
              الطالب: يمتحن ويلاقي نتيجته وتحليله فوراً
            </li>
          </ul>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex-1 flex flex-col justify-center px-6 py-12 sm:px-12 lg:px-20">
        <div className="w-full max-w-md mx-auto">
          <h2 className="font-display text-3xl text-ink">أنشئ حساب جديد ✨</h2>
          <p className="text-sm text-cocoa-500 mt-1 mb-7">اختار نوع الحساب وكمّل بياناتك</p>

          {error && (
            <Alert type="error" className="mb-5" onClose={() => setError('')} message={error} />
          )}

          <form className="space-y-4" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="name" className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                الاسم بالكامل
              </label>
              <div className="relative rounded-2xl">
                <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-cocoa-300">
                  <User className="w-4 h-4" />
                </div>
                <input
                  id="name"
                  name="name"
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="د. أحمد محمود أو محمد سمير"
                  className="block w-full ps-11 pe-4 py-3 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                />
              </div>
            </div>

            <div>
              <label htmlFor="email" className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                البريد الإلكتروني
              </label>
              <div className="relative rounded-2xl">
                <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-cocoa-300">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="user@school.edu.eg"
                  className="block w-full ps-11 pe-4 py-3 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-[13px] font-bold text-cocoa-800 mb-1.5">
                كلمة المرور (٦ حروف على الأقل)
              </label>
              <div className="relative rounded-2xl">
                <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-cocoa-300">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="block w-full ps-11 pe-4 py-3 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-[13px] font-bold text-cocoa-800 mb-2">
                نوع الحساب
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setRole('student')}
                  className={`py-3 px-3 rounded-2xl border-2 text-sm font-bold transition-all text-center ${
                    role === 'student'
                      ? 'bg-teal-50 border-teal-700 text-teal-800 -rotate-1 shadow-warm'
                      : 'border-cocoa-300/60 text-cocoa-500 hover:bg-sand/60'
                  }`}
                >
                  📚 طالب
                </button>
                <button
                  type="button"
                  onClick={() => setRole('professor')}
                  className={`py-3 px-3 rounded-2xl border-2 text-sm font-bold transition-all text-center ${
                    role === 'professor'
                      ? 'bg-clay-50 border-clay-700 text-clay-800 rotate-1 shadow-warm'
                      : 'border-cocoa-300/60 text-cocoa-500 hover:bg-sand/60'
                  }`}
                >
                  🎓 أستاذ
                </button>
              </div>
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              className="w-full mt-3 btn-cut"
              icon={UserPlus}
            >
              إنشاء الحساب
            </Button>
          </form>

          <p className="mt-6 text-[13.5px] text-cocoa-500 text-center">
            عندك حساب بالفعل؟{' '}
            <Link to="/login" className="font-bold text-clay-700 hover:text-clay-600 hover:underline">
              سجّل دخول من هنا
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default RegisterPage;
