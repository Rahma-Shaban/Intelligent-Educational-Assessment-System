import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Button from '../components/ui/Button';
import Alert from '../components/ui/Alert';
import { Mail, Lock, LogIn } from 'lucide-react';
import { BrandMark } from '../components/Layout';

const LoginPage = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const user = await login(email, password);
      const destination =
        location.state?.from?.pathname ||
        (user.role === 'professor' ? '/professor/dashboard' : '/student/dashboard');
      navigate(destination, { replace: true });
    } catch (err) {
      console.error('Login error:', err);
      const msg =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'البريد الإلكتروني أو كلمة المرور غير صحيحة، حاول تاني.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream flex flex-col lg:flex-row">
      {/* Branded art panel — programming vibe */}
      <div className="relative lg:w-[46%] bg-gradient-to-bl from-clay-600 via-clay-800 to-clay-950 text-white px-8 py-10 lg:px-12 lg:py-12 flex flex-col overflow-hidden">
        <div className="absolute -top-20 -start-20 w-64 h-64 rounded-full bg-gold-400/20 blur-3xl" />
        <div className="absolute bottom-10 end-0 w-52 h-52 rounded-full bg-gold-500/10 blur-2xl" />

        {/* floating code chips */}
        <span className="code-chip-light absolute top-24 end-8 rotate-3 hidden md:inline-block">print("Hello, IAS")</span>
        <span className="code-chip-light absolute top-40 end-28 -rotate-2 hidden md:inline-block">for attempt in exams:</span>

        <div className="flex items-center gap-3 relative z-10">
          <BrandMark size="lg" />
          <div>
            <h2 className="font-display text-3xl leading-none pt-1">
              IA<span className="text-gold-300">S</span>
            </h2>
            <p className="text-[12px] font-semibold text-clay-100 mt-1">منصة التقييم التعليمي الذكية</p>
          </div>
        </div>

        <div className="relative z-10 mt-10 lg:mt-auto mb-8">
          <span className="sticker border-white/60 bg-white/10 text-gold-200 -rotate-1">
            🎓 منهج Programming & Computer Science — بكالوريا
          </span>
          <h1 className="font-display text-4xl lg:text-[2.6rem] leading-snug mt-5">
            امتحانك يتولّد بالذكاء
            <br />
            <span className="text-gold-300">وتصحيحه ييجي فوراً ⚡</span>
          </h1>
          <p className="text-clay-100 text-sm leading-relaxed mt-4 max-w-md">
            ارفع ملف المقرر بالإنجليزي، والمنصة تولّد أسئلة منه من محتواه، تصحّحها آلياً،
            وتحلّل مستوى كل طالب.
          </p>

          {/* terminal window */}
          <div className="term mt-7 max-w-sm">
            <div className="term-bar">
              <span className="term-dot bg-rose-400" />
              <span className="term-dot bg-gold-400" />
              <span className="term-dot bg-teal-400" />
            </div>
            <div className="term-body text-gold-200">
              <p><span className="text-teal-300">$</span> ias generate --curriculum <span className="text-white">CS-Bac2.pdf</span></p>
              <p className="text-cocoa-300"># retrieving context ... ✓</p>
              <p><span className="text-teal-300">$</span> grading <span className="text-gold-300">--instant</span> <span className="text-cocoa-300"># ⚡</span></p>
            </div>
          </div>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex-1 flex flex-col justify-center px-6 py-12 sm:px-12 lg:px-20">
        <div className="w-full max-w-md mx-auto">
          <h2 className="font-display text-3xl text-ink">أهلاً بيك تاني 👋</h2>
          <p className="text-sm text-cocoa-500 mt-1 mb-7">سجّل دخولك وكمّل من حيث وقفت</p>

          {error && (
            <Alert type="error" className="mb-5" onClose={() => setError('')} message={error} />
          )}

          <form className="space-y-5" onSubmit={handleSubmit}>
            <div>
              <label
                htmlFor="email"
                className="block text-[13px] font-bold text-cocoa-800 mb-1.5"
              >
                البريد الإلكتروني
              </label>
              <div className="relative rounded-2xl shadow-sm">
                <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-cocoa-300">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="user@school.edu.eg"
                  className="block w-full ps-11 pe-4 py-3 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-[13px] font-bold text-cocoa-800 mb-1.5"
              >
                كلمة المرور
              </label>
              <div className="relative rounded-2xl shadow-sm">
                <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-cocoa-300">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="block w-full ps-11 pe-4 py-3 text-sm bg-white border-2 border-cocoa-300/60 rounded-2xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 transition outline-none"
                />
              </div>
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              className="w-full mt-2 btn-cut"
              icon={LogIn}
            >
              يلا نبدأ
            </Button>
          </form>

          <p className="mt-7 text-[13.5px] text-cocoa-500 text-center">
            لسه معندكش حساب؟{' '}
            <Link to="/register" className="font-bold text-clay-700 hover:text-clay-600 hover:underline">
              سجّل في المنصة
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
