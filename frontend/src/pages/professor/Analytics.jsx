import React, { useState, useEffect } from 'react';
import { runClustering, getProfessorDashboard } from '../../api/client';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import Alert from '../../components/ui/Alert';
import {
  BarChart3,
  Network,
  Users,
  TrendingUp,
  AlertTriangle,
  Award,
  Search,
  Filter,
  CheckCircle,
  HelpCircle,
} from 'lucide-react';

const Analytics = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [clusteringRunning, setClusteringRunning] = useState(false);
  const [error, setError] = useState('');
  const [clusterSuccess, setClusterSuccess] = useState('');
  const [activeClusterTab, setActiveClusterTab] = useState('all');

  const fetchAnalytics = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getProfessorDashboard();
      setData(res);
    } catch (err) {
      console.warn('Failed to load professor dashboard analytics:', err);
      // Generate clean demonstration data if endpoint is fresh or empty
      setData({
        class_analytics: {
          avg_score_pct: 0,
          total_students: 0,
          total_attempts: 0,
          topic_performance: {},
        },
        clusters: [],
        students: [],
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const handleRunClustering = async () => {
    setClusteringRunning(true);
    setError('');
    setClusterSuccess('');
    try {
      const clusterResult = await runClustering();
      setClusterSuccess('نموذج التجميع الذكي اتحدّث بنجاح! 🎉');
      // Refresh analytics data
      if (clusterResult && (clusterResult.clusters || clusterResult.students)) {
        setData((prev) => ({
          ...prev,
          ...clusterResult,
        }));
      } else {
        await fetchAnalytics();
      }
    } catch (err) {
      console.error('Clustering error:', err);
      const msg =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        'فشل تشغيل التجميع الذكي. تأكد إن فيه محاولات امتحانات مسجّلة في قاعدة البيانات.';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setClusteringRunning(false);
    }
  };

  if (loading) {
    return <LoadingSpinner size="lg" message="جاري حساب تحليلات الفصل..." />;
  }

  const clusterItems = Array.isArray(data?.clusters) ? data.clusters : [];
  const clusters = Array.isArray(data?.clusters)
    ? clusterItems.reduce(
        (acc, c) => {
          const lbl = String(c.cluster_label || c.label || '').toLowerCase();
          if (lbl.includes('intervention') || lbl.includes('risk')) {
            acc.needs_intervention = (acc.needs_intervention || 0) + 1;
          } else if (lbl.includes('advanced')) {
            acc.advanced = (acc.advanced || 0) + 1;
          } else {
            acc.proficient = (acc.proficient || 0) + 1;
          }
          return acc;
        },
        { advanced: 0, proficient: 0, needs_intervention: 0 }
      )
    : data?.clusters || { advanced: 0, proficient: 0, needs_intervention: 0 };

  const totalClusterStudents =
    Object.values(clusters).reduce((a, b) => a + (Number(b) || 0), 0) || (clusterItems.length || 1);
  const advancedPct = Math.round(((clusters.advanced || 0) / totalClusterStudents) * 100);
  const proficientPct = Math.round(((clusters.proficient || 0) / totalClusterStudents) * 100);
  const interventionPct = Math.round(
    ((clusters.needs_intervention || clusters.at_risk || 0) / totalClusterStudents) * 100
  );

  const studentsList = Array.isArray(data?.students)
    ? data.students
    : clusterItems.map((c) => ({
        id: c.student_id,
        name: c.student_name || `Student #${c.student_id}`,
        email: c.student_email || `student${c.student_id}@univ.edu`,
        cluster: c.cluster_label,
        score: c.features?.avg_percentage ?? c.features?.score ?? c.score,
        attempts: c.features?.exams_taken ?? c.attempts ?? 1,
      }));

  const avgScore =
    data?.class_analytics?.avg_score_pct ??
    data?.average_score ??
    0;
  const totalStudents =
    data?.class_analytics?.total_students ??
    data?.total_students ??
    clusterItems.length;
  const totalAttempts =
    data?.class_analytics?.total_attempts ??
    data?.total_attempts ??
    0;

  const topicPerformance = Array.isArray(data?.topic_performance)
    ? data.topic_performance
    : data?.class_analytics?.topic_performance && typeof data.class_analytics.topic_performance === 'object'
    ? Object.entries(data.class_analytics.topic_performance).map(([topic, score]) => ({
        topic,
        score: typeof score === 'number' ? score : (score?.average || 0),
      }))
    : [];

  const filteredStudents = studentsList.filter((s) => {
    if (activeClusterTab === 'all') return true;
    const clusterName = String(s.cluster || s.group || '').toLowerCase();
    if (activeClusterTab === 'needs_intervention') {
      return clusterName.includes('intervention') || clusterName.includes('risk');
    }
    return clusterName.includes(activeClusterTab);
  });

  return (
    <div className="space-y-8">
      {/* Title & Trigger Button */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="relative">
          <span className="code-chip absolute -top-3 end-0 rotate-2 hidden md:inline-block">clusters = kmeans(students)</span>
          <h1 className="font-display text-3xl md:text-4xl text-ink">الإحصائيات والتحليلات 📊</h1>
          <p className="text-sm text-cocoa-500 mt-1 leading-relaxed">
            التعلم الآلي بيصنّف الطلبة لمجموعات مستويات عشان تكتشف مواضيع الضعف والطلبة المحتاجين مساعدة.
          </p>
        </div>
        <Button
          variant="primary"
          size="md"
          loading={clusteringRunning}
          onClick={handleRunClustering}
          icon={Network}
          className="btn-cut shrink-0"
        >
          {clusteringRunning ? 'جاري التجميع...' : 'شغّل التجميع الذكي'}
        </Button>
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError('')} />}
      {clusterSuccess && (
        <Alert type="success" message={clusterSuccess} onClose={() => setClusterSuccess('')} />
      )}

      {/* Cluster Distribution Overview */}
      <Card
        title="توزيع مستوى الطلبة"
        subtitle="التقسيم الحالي لمجموعات التعلم"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="p-4 rounded-2xl border-2 border-clay-200 bg-clay-50/50 !border-t-4 !border-t-clay-600">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-clay-700">
                متقدمين (Advanced)
              </span>
              <span className="sticker !text-[10px] !py-0.5 text-clay-700" style={{ borderWidth: 1.5 }}>
                {advancedPct}%
              </span>
            </div>
            <p className="font-display text-3xl text-clay-700 mt-2">
              {clusters.advanced || 0}
            </p>
            <p className="text-xs text-cocoa-500 mt-1 font-semibold">
              فهم عميق وإجابات متسقة
            </p>
          </div>

          <div className="p-4 rounded-2xl border-2 border-teal-200 bg-teal-50/50 !border-t-4 !border-t-teal-700">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-teal-700">
                متمكنين (Proficient)
              </span>
              <span className="sticker !text-[10px] !py-0.5 text-teal-700" style={{ borderWidth: 1.5 }}>
                {proficientPct}%
              </span>
            </div>
            <p className="font-display text-3xl text-teal-700 mt-2">
              {clusters.proficient || 0}
            </p>
            <p className="text-xs text-cocoa-500 mt-1 font-semibold">
              فهم قوي مع فجوات بسيطة
            </p>
          </div>

          <div className="p-4 rounded-2xl border-2 border-rose-200 bg-rose-50/50 !border-t-4 !border-t-rose-500">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-rose-700">
                محتاجين متابعة (Intervention)
              </span>
              <span className="sticker !text-[10px] !py-0.5 text-rose-600" style={{ borderWidth: 1.5 }}>
                {interventionPct}%
              </span>
            </div>
            <p className="font-display text-3xl text-rose-600 mt-2">
              {clusters.needs_intervention || clusters.at_risk || 0}
            </p>
            <p className="text-xs text-cocoa-500 mt-1 font-semibold">
              أخطاء متكررة وفجوات في الفهم
            </p>
          </div>
        </div>

        {/* Visual Stacked Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-cocoa-500 font-bold">
            <span>طيف توزيع الفصل</span>
            <span>{totalClusterStudents} طالب مُقيَّم</span>
          </div>
          <div className="w-full h-3.5 bg-sand rounded-full flex overflow-hidden shadow-inner">
            <div
              style={{ width: `${advancedPct}%` }}
              className="bg-gradient-to-l from-clay-600 to-clay-500 h-full transition-all duration-500"
              title={`Advanced: ${advancedPct}%`}
            />
            <div
              style={{ width: `${proficientPct}%` }}
              className="bg-teal-500 h-full transition-all duration-500"
              title={`Proficient: ${proficientPct}%`}
            />
            <div
              style={{ width: `${interventionPct}%` }}
              className="bg-rose-500 h-full transition-all duration-500"
              title={`Needs Intervention: ${interventionPct}%`}
            />
          </div>
          <div className="flex items-center gap-6 text-[11px] text-cocoa-500 pt-1 font-bold">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-clay-600 inline-block" />
              <span>متقدمين ({advancedPct}%)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-teal-500 inline-block" />
              <span>متمكنين ({proficientPct}%)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" />
              <span>محتاجين متابعة ({interventionPct}%)</span>
            </div>
          </div>
        </div>
      </Card>

      {/* Topic Mastery Bars & Class Averages */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="أداء المواضيع" subtitle="متوسط درجات الفصل لكل مجال في المنهج">
          <div className="space-y-4 mt-2">
            {(topicPerformance || []).length === 0 ? (
              <p className="text-xs text-cocoa-500 py-4 text-center">لسه مفيش بيانات أداء للمواضيع.</p>
            ) : (
              (topicPerformance || []).map((tp, idx) => {
                const score = tp.score || tp.average || 0;
                const barColor =
                  score >= 80
                    ? 'bg-teal-600'
                    : score >= 70
                    ? 'bg-gradient-to-l from-clay-600 to-clay-500'
                    : 'bg-gold-500';

                return (
                  <div key={idx} className="space-y-1">
                    <div className="flex justify-between text-xs font-bold">
                      <span className="text-cocoa-800" dir="auto">{tp.topic}</span>
                      <span className="text-ink font-extrabold">{Math.round(score)}%</span>
                    </div>
                    <div className="w-full bg-sand rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full ${barColor} transition-all duration-500`}
                        style={{ width: `${score}%` }}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </Card>

        <Card title="مؤشرات الفصل" subtitle="نظرة عامة على تفاعل الطلبة">
          <div className="grid grid-cols-2 gap-4 mt-2">
            <div className="p-4 bg-cream rounded-2xl border border-sand">
              <p className="text-xs text-cocoa-500 font-bold">متوسط درجات الفصل</p>
              <h4 className="font-display text-2xl text-clay-700 mt-1">
                {avgScore ? `${Math.round(avgScore)}%` : '0%'}
              </h4>
              <p className="text-[11px] text-teal-700 font-bold mt-1">حد النجاح: ٦٠٪</p>
            </div>

            <div className="p-4 bg-cream rounded-2xl border border-sand">
              <p className="text-xs text-cocoa-500 font-bold">إجمالي المحاولات</p>
              <h4 className="font-display text-2xl text-teal-700 mt-1">
                {totalAttempts}
              </h4>
              <p className="text-[11px] text-cocoa-500 font-semibold mt-1">تقييمات آلية</p>
            </div>

            <div className="p-4 bg-cream rounded-2xl border border-sand">
              <p className="text-xs text-cocoa-500 font-bold">تنبيهات الطلبة</p>
              <h4 className="font-display text-2xl text-rose-600 mt-1">
                {clusters.needs_intervention || 0}
              </h4>
              <p className="text-[11px] text-rose-500 font-bold mt-1">محتاجين مراجعة</p>
            </div>

            <div className="p-4 bg-cream rounded-2xl border border-sand">
              <p className="text-xs text-cocoa-500 font-bold">عدد الطلبة</p>
              <h4 className="font-display text-2xl text-cocoa-800 mt-1">
                {totalStudents}
              </h4>
              <p className="text-[11px] text-cocoa-500 font-semibold mt-1">مسجلين في الفصل</p>
            </div>
          </div>
        </Card>
      </div>

      {/* Student List Grouped by Cluster */}
      <Card
        title="قائمة الطلبة حسب المجموعة"
        subtitle="ملفات الطلبة وتصنيف أنماط تعلمهم"
        action={
          <div className="flex gap-1.5 bg-sand p-1 rounded-xl text-xs">
            {[
              { key: 'all', label: 'الكل' },
              { key: 'advanced', label: 'متقدمين' },
              { key: 'proficient', label: 'متمكنين' },
              { key: 'needs_intervention', label: 'محتاجين متابعة' },
            ].map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveClusterTab(tab.key)}
                className={`px-3 py-1 rounded-lg font-bold transition-all ${
                  activeClusterTab === tab.key
                    ? 'bg-paper text-ink shadow-sm'
                    : 'text-cocoa-500 hover:text-ink'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        }
      >
        {filteredStudents.length === 0 ? (
          <div className="text-center py-8 text-cocoa-500 text-xs">
            مفيش طلبة في التصنيف المختار.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-right divide-y divide-sand">
              <thead className="bg-cream text-cocoa-500 font-bold text-[11px]">
                <tr>
                  <th className="px-4 py-3">اسم الطالب</th>
                  <th className="px-4 py-3">البريد الإلكتروني</th>
                  <th className="px-4 py-3">التصنيف</th>
                  <th className="px-4 py-3 text-center">المحاولات</th>
                  <th className="px-4 py-3">المتوسط</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sand bg-paper">
                {filteredStudents.map((student, idx) => {
                  const sCluster = student.cluster || student.group || 'proficient';
                  return (
                    <tr key={student.id || idx} className="hover:bg-cream/60 transition-colors">
                      <td className="px-4 py-3 font-bold text-ink flex items-center gap-2">
                        <div className="w-7 h-7 rounded-lg rounded-br-sm bg-clay-100 text-clay-700 font-bold flex items-center justify-center text-[11px]">
                          {student.name ? student.name.charAt(0).toUpperCase() : 'S'}
                        </div>
                        <span>{student.name}</span>
                      </td>
                      <td className="px-4 py-3 text-cocoa-500 font-code text-[11px]" dir="ltr">{student.email}</td>
                      <td className="px-4 py-3">
                        <Badge type="cluster">{sCluster}</Badge>
                      </td>
                      <td className="px-4 py-3 text-center text-cocoa-500 font-bold">
                        {student.attempts || student.num_attempts || 1}
                      </td>
                      <td className="px-4 py-3 font-extrabold text-ink">
                        {student.score !== undefined ? `${Math.round(student.score)}%` : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};

export default Analytics;
