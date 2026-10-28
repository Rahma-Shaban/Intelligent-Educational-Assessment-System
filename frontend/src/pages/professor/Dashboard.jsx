import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getProfessorDashboard, getExams } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  FileUp,
  Sparkles,
  BookOpen,
  Users,
  Award,
  TrendingUp,
  ArrowLeft,
  Clock,
  CheckCircle,
  AlertCircle,
  HelpCircle,
  Code2,
} from 'lucide-react';

const ProfessorDashboard = () => {
  const { user } = useAuth();
  const [dashboardData, setDashboardData] = useState(null);
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const [dashRes, examsRes] = await Promise.allSettled([
          getProfessorDashboard(),
          getExams(),
        ]);

        if (dashRes.status === 'fulfilled') {
          setDashboardData(dashRes.value);
        } else {
          console.warn('Professor dashboard analytics endpoint failed or empty:', dashRes.reason);
        }

        if (examsRes.status === 'fulfilled') {
          setExams(Array.isArray(examsRes.value) ? examsRes.value : examsRes.value?.exams || []);
        } else {
          console.warn('Exams fetch failed:', examsRes.reason);
        }
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
        setError(' قدرنا نجيب جزء من بيانات اللوحة فقط. يتم استخدام المتاح حالياً.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري تحميل المنصة ..." />;
  }

  // Derive stats either from dashboard endpoint or exam collection
  const totalExams = dashboardData?.total_exams ?? exams.length;
  const totalStudents =
    dashboardData?.class_analytics?.total_students ??
    dashboardData?.total_students ??
    dashboardData?.student_count ??
    (Array.isArray(dashboardData?.clusters) ? dashboardData.clusters.length : 0);
  const rawAvg =
    dashboardData?.class_analytics?.avg_score_pct ??
    dashboardData?.average_score ??
    dashboardData?.avg_score;
  const avgScore = rawAvg !== undefined && rawAvg !== null ? `${Math.round(rawAvg)}%` : '0%';
  const totalAttempts =
    dashboardData?.class_analytics?.total_attempts ??
    dashboardData?.total_attempts ??
    0;

  // Safely aggregate cluster distribution whether clusters is an array or an object map
  const clusterCounts = Array.isArray(dashboardData?.clusters)
    ? dashboardData.clusters.reduce((acc, c) => {
        const lbl = String(c.cluster_label || c.label || 'Proficient');
        acc[lbl] = (acc[lbl] || 0) + 1;
        return acc;
      }, {})
    : dashboardData?.cluster_summary ||
      (dashboardData?.clusters && typeof dashboardData.clusters === 'object' && !Array.isArray(dashboardData.clusters)
        ? dashboardData.clusters
        : null);

  const hasClusterData = clusterCounts && Object.keys(clusterCounts).length > 0;
  const recentExams = exams.slice(0, 5);

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-gradient-to-bl from-clay-700 via-clay-800 to-clay-950 rounded-3xl p-6 md:p-8 text-white shadow-pop">
        <span className="code-chip-light absolute top-5 end-6 rotate-2 hidden md:inline-block">generate_exam(lesson=...)</span>
        <div className="absolute -bottom-16 -start-10 w-56 h-56 rounded-full bg-gold-400/10 blur-2xl" />
        <div className="relative z-10">
          <h1 className="font-display text-3xl md:text-4xl leading-snug">
            أهلاً أ. <span className="text-gold-300">{user?.name || 'أستاذ'}</span>
          </h1>
          <p className="text-clay-100 text-sm mt-2 max-w-xl leading-relaxed">
            ولّد امتحانات وتابع مستوى الطلبة.
          </p>
          <span className="sticker border-gold-400/60 bg-white/10 text-gold-200 mt-4 inline-flex">
            📘 Programming & Computer Science — تانية بكالوريا
          </span>
        </div>
        <div className="relative z-10 flex flex-wrap gap-2.5">
          <Link to="/professor/curriculum">
            <Button variant="secondary" size="md" icon={FileUp} className="bg-white/10 hover:bg-white/20 text-white border-white/20">
              رفع منهج
            </Button>
          </Link>
          <Link to="/professor/generate">
            <Button variant="secondary" size="md" icon={Sparkles} className="bg-gold-400 text-clay-950 hover:bg-gold-300 border-none font-bold">
              إنشاء امتحان ✨
            </Button>
          </Link>
        </div>
      </div>

      {error && <Alert type="warning" message={error} onClose={() => setError('')} />}

      {/* Overview Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Card className="hover:border-clay-200 !border-t-4 !border-t-clay-600">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">إجمالي الامتحانات</p>
              <h3 className="font-display text-3xl text-clay-700 mt-1">{totalExams}</h3>
            </div>
            <div className="w-12 h-12 bg-clay-100 text-clay-700 rounded-2xl rounded-br-sm flex items-center justify-center">
              <BookOpen className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-teal-200 !border-t-4 !border-t-teal-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">طلبة مشاركين</p>
              <h3 className="font-display text-3xl text-teal-700 mt-1">{totalStudents}</h3>
            </div>
            <div className="w-12 h-12 bg-teal-50 text-teal-700 rounded-2xl rounded-br-sm flex items-center justify-center">
              <Users className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-gold-200 !border-t-4 !border-t-gold-400">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">متوسط الدرجات</p>
              <h3 className="font-display text-3xl text-gold-600 mt-1">{avgScore}</h3>
            </div>
            <div className="w-12 h-12 bg-gold-100 text-gold-600 rounded-2xl rounded-br-sm flex items-center justify-center">
              <Award className="w-6 h-6" />
            </div>
          </div>
        </Card>

        <Card className="hover:border-cocoa-300 !border-t-4 !border-t-cocoa-500">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-cocoa-500">محاولات مسلّمة</p>
              <h3 className="font-display text-3xl text-cocoa-800 mt-1">{totalAttempts}</h3>
            </div>
            <div className="w-12 h-12 bg-sand text-cocoa-800 rounded-2xl rounded-br-sm flex items-center justify-center">
              <TrendingUp className="w-6 h-6" />
            </div>
          </div>
        </Card>
      </div>

      {/* Two Column Section: Recent Exams & Class Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Recent Exams List (2 cols on large screen) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-clay-600" />
              أحدث الامتحانات
            </h2>
            <Link
              to="/professor/exams"
              className="text-xs font-bold text-clay-700 hover:text-clay-600 flex items-center gap-1"
            >
              عرض الكل ({exams.length}) <ArrowLeft className="w-3.5 h-3.5" />
            </Link>
          </div>

          {recentExams.length === 0 ? (
            <Card className="text-center py-12">
              <div className="w-14 h-14 bg-clay-100 text-clay-600 rounded-2xl rounded-br-sm flex items-center justify-center mx-auto mb-3 -rotate-3">
                <Code2 className="w-7 h-7" />
              </div>
              <h4 className="text-base font-bold text-ink">لسه مفيش امتحانات متولّدة</h4>
              <p className="text-xs text-cocoa-500 mt-1 max-w-sm mx-auto leading-relaxed">
                ارفع ملف المنهج الأول، وسيب للذكاء الاصطناعي يولّد أسئلة منه.
              </p>
              <div className="mt-4">
                <Link to="/professor/generate">
                  <Button size="sm" icon={Sparkles}>
                    ولّد أول امتحان
                  </Button>
                </Link>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {recentExams.map((exam) => {
                const examId = exam.id || exam._id || exam.exam_id;
                const questionCount =
                  exam.questions?.length || exam.question_count || exam.num_questions || 0;
                const totalPoints =
                  exam.total_points ||
                  exam.max_score ||
                  (exam.questions ? exam.questions.reduce((acc, q) => acc + (q.max_score || 1), 0) : 0);

                return (
                  <Card
                    key={examId || Math.random()}
                    className="p-5 hover:border-gold-400 transition-all cursor-pointer"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Link
                            to={`/professor/exams/${examId}`}
                            className="font-bold text-ink hover:text-clay-600 transition-colors"
                            dir="auto"
                          >
                            {exam.title || exam.topic || `Exam #${examId}`}
                          </Link>
                          {exam.difficulty && (
                            <Badge type="difficulty">{exam.difficulty}</Badge>
                          )}
                          {exam.bloom_level && (
                            <Badge type="bloom">{exam.bloom_level}</Badge>
                          )}
                        </div>
                        <p className="text-xs text-cocoa-500" dir="auto">
                          {exam.lesson_title || exam.lesson || (exam.topic && `Topic: ${exam.topic}`) || 'امتحان من المنهج'}
                        </p>
                      </div>

                      <div className="flex items-center gap-3 text-xs text-cocoa-500 shrink-0">
                        <span className="bg-cream px-2.5 py-1 rounded-lg border border-sand font-bold">
                          {questionCount} سؤال
                        </span>
                        <span className="bg-cream px-2.5 py-1 rounded-lg border border-sand font-bold">
                          {totalPoints} درجة
                        </span>
                        <Link to={`/professor/exams/${examId}`}>
                          <Button variant="outline" size="sm">
                            التفاصيل
                          </Button>
                        </Link>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        {/* Class Performance Summary / Quick Analytics (1 col) */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-extrabold text-ink flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-clay-600" />
              لمحة سريعة
            </h2>
            <Link
              to="/professor/analytics"
              className="text-xs font-bold text-clay-700 hover:text-clay-600"
            >
              التحليلات الكاملة ←
            </Link>
          </div>

          <Card title="توزيع مستوى الطلبة" subtitle="حسب مجموعات الذكاء الاصطناعي">
            {hasClusterData ? (
              <div className="space-y-3 mt-2">
                {Object.entries(clusterCounts).map(([name, count]) => (
                  <div key={name} className="flex items-center justify-between text-xs">
                    <span className="font-bold text-cocoa-800">{name}</span>
                    <span className="font-bold text-clay-700 bg-clay-100 px-2 py-0.5 rounded-full">
                      {count} طالب
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-6 text-cocoa-500 space-y-2">
                <HelpCircle className="w-8 h-8 mx-auto text-cocoa-300" />
                <p className="text-xs">لسه مفيش تجميع (Clustering) للفصل ده.</p>
                <Link to="/professor/analytics">
                  <Button variant="outline" size="sm" className="mt-2 text-xs">
                    شغّل التجميع الذكي
                  </Button>
                </Link>
              </div>
            )}
          </Card>

          <Card title="إزاي تبدأ؟">
            <ul className="space-y-3 text-xs text-cocoa-500 leading-relaxed">
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-lg rounded-br-sm bg-clay-100 text-clay-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  ١
                </span>
                <span>
                  <strong className="text-cocoa-800">ارفع المنهج:</strong> ارفع الكتاب أو المحاضرات PDF عشان المنصة تفهم محتواه.
                </span>
              </li>
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-lg rounded-br-sm bg-clay-100 text-clay-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  ٢
                </span>
                <span>
                  <strong className="text-cocoa-800">اضبط التوليد:</strong> اختار مستوى بلوم والصعوبة وعدد الأسئلة.
                </span>
              </li>
              <li className="flex items-start gap-2.5">
                <span className="w-5 h-5 rounded-lg rounded-br-sm bg-clay-100 text-clay-700 font-bold flex items-center justify-center shrink-0 text-[11px]">
                  ٣
                </span>
                <span>
                  <strong className="text-cocoa-800">حلّل النتائج:</strong> شوف الطلبة اللي محتاجين مساعدة ومواضيع الضعف.
                </span>
              </li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default ProfessorDashboard;
