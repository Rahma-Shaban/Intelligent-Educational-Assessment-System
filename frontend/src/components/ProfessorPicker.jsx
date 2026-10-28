import React, { useEffect, useState } from 'react';
import { getProfessors, selectProfessor } from '../api/client';
import { useAuth } from '../context/AuthContext';
import Card from './ui/Card';
import Button from './ui/Button';
import Alert from './ui/Alert';
import LoadingSpinner from './ui/LoadingSpinner';
import { GraduationCap, UserCheck, AlertTriangle } from 'lucide-react';

/**
 * Lets a student pick (and change) the professor they are enrolled with.
 * The selection is persisted on the backend account, not just locally.
 * Calls onSaved() after a successful change so pages can refetch scoped data.
 */
const ProfessorPicker = ({ onSaved }) => {
  const { user, updateUser } = useAuth();
  const [professors, setProfessors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [pickedId, setPickedId] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState('');

  const currentProfessorId = user?.selected_professor_id ?? null;

  useEffect(() => {
    const fetchProfessors = async () => {
      setLoading(true);
      setLoadError('');
      try {
        const data = await getProfessors();
        const list = Array.isArray(data) ? data : [];
        setProfessors(list);
        setPickedId(currentProfessorId ? String(currentProfessorId) : '');
      } catch (err) {
        console.error('Failed to load professors list:', err);
        setLoadError('فشل تحميل قائمة الأساتذة. حاول تاني.');
      } finally {
        setLoading(false);
      }
    };

    fetchProfessors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentProfessor = professors.find((p) => p.id === currentProfessorId);

  const handleSave = async () => {
    setSaveError('');
    setSaveSuccess('');
    if (!pickedId) {
      setSaveError('اختار أستاذ الأول.');
      return;
    }
    setSaving(true);
    try {
      const updatedUser = await selectProfessor(Number.parseInt(pickedId, 10));
      updateUser(updatedUser);
      setSaveSuccess(
        `تم اختيار أستاذك: ${updatedUser.name || currentProfessor?.name || 'الأستاذ'} — دلوقتي بتشوف امتحاناته بس.`
      );
      if (onSaved) onSaved();
    } catch (err) {
      console.error('Failed to select professor:', err);
      const detail = err.response?.data?.detail || err.message || 'فشل حفظ الاختيار.';
      setSaveError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Card className="p-4">
        <LoadingSpinner size="sm" message="جاري تحميل قائمة الأساتذة..." />
      </Card>
    );
  }

  return (
    <Card
      className={`border-2 ${
        currentProfessorId ? 'border-teal-200 bg-teal-50/40' : 'border-gold-300 bg-gold-50/50'
      }`}
    >
      <div className="flex flex-col md:flex-row md:items-center gap-4 justify-between">
        <div className="flex items-start gap-3">
          <div
            className={`w-11 h-11 rounded-2xl rounded-br-sm flex items-center justify-center shrink-0 rotate-2 ${
              currentProfessorId ? 'bg-teal-700 text-white' : 'bg-gold-400 text-clay-950'
            }`}
          >
            {currentProfessorId ? <UserCheck className="w-6 h-6" /> : <GraduationCap className="w-6 h-6" />}
          </div>
          <div>
            <h3 className="text-sm font-extrabold text-ink">
              {currentProfessorId ? 'أستاذك الحالي' : 'اختار أستاذك الأول'}
            </h3>
            {currentProfessorId ? (
              <p className="text-xs text-cocoa-600 mt-0.5">
                {currentProfessor
                  ? `${currentProfessor.name} • ${currentProfessor.email}`
                  : `معرّف الأستاذ: ${currentProfessorId}`}
                <span className="text-cocoa-400"> — بتشوف امتحاناته هو بس.</span>
              </p>
            ) : (
              <p className="text-xs text-cocoa-600 mt-0.5 flex items-start gap-1.5 max-w-md">
                <AlertTriangle className="w-3.5 h-3.5 text-gold-700 shrink-0 mt-0.5" />
                لازم تختار الأستاذ اللي ب تدرس معاه عشان تظهر لك امتحاناته المنشورة.
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full md:w-auto">
          {loadError ? (
            <Alert type="error" message={loadError} />
          ) : professors.length === 0 ? (
            <p className="text-xs text-cocoa-500">مفيش أساتذة مسجلين في المنصة لسه.</p>
          ) : (
            <>
              <select
                value={pickedId}
                onChange={(e) => {
                  setPickedId(e.target.value);
                  setSaveSuccess('');
                  setSaveError('');
                }}
                className="px-3 py-2 text-sm font-bold bg-white border-2 border-cocoa-300/60 rounded-xl focus:ring-4 focus:ring-gold-400/20 focus:border-gold-500 outline-none transition"
                aria-label="اختار الأستاذ"
              >
                <option value="">— اختار الأستاذ —</option>
                {professors.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name}
                  </option>
                ))}
              </select>
              <Button
                variant="primary"
                size="sm"
                loading={saving}
                onClick={handleSave}
                disabled={!pickedId || Number.parseInt(pickedId, 10) === currentProfessorId}
                className="btn-cut shrink-0"
              >
                تأكيد الاختيار
              </Button>
            </>
          )}
        </div>
      </div>

      {saveError && (
        <div className="mt-3">
          <Alert type="error" message={saveError} onClose={() => setSaveError('')} />
        </div>
      )}
      {saveSuccess && (
        <div className="mt-3">
          <Alert type="success" message={saveSuccess} onClose={() => setSaveSuccess('')} />
        </div>
      )}
    </Card>
  );
};

export default ProfessorPicker;
