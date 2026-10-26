import { useEffect, useState } from 'react';
import { deleteProfileField, getProfile, resetProfile, updateProfile } from '../api/profile';
import type { OnboardingField, PersonalizationProfile } from '../types/profile';
import { nextOnboardingField, recordOnboardingAnswer, recordOnboardingSkip } from '../utils/onboarding';

type Question = { key: keyof PersonalizationProfile; tr: string; en: string; kind?: 'age' | 'life' | 'frequency' | 'list' | 'goal' };
const questions: Question[] = [
  { key: 'preferred_name', tr: 'Size nasıl hitap etmemizi istersiniz?', en: 'What name would you like us to use?' },
  { key: 'age_range', tr: 'İsteğe bağlı: yaş aralığınızı paylaşmak ister misiniz?', en: 'Optional: would you like to share your age range?', kind: 'age' },
  { key: 'life_context', tr: 'Şu anki yaşam bağlamınız hangisi?', en: 'Which best describes your current life context?', kind: 'life' },
  { key: 'field_of_study', tr: 'Bir eğitim alanınız var mı?', en: 'Do you have a field of study?' },
  { key: 'study_year', tr: 'Eğitim yılınız nedir?', en: 'What is your study year?' },
  { key: 'deadlines_goals', tr: 'Yaklaşan hedeflerinizi yazın (başlık | YYYY-MM-DD | goal/exam/deadline).', en: 'Add goals (title | YYYY-MM-DD | goal/exam/deadline).', kind: 'goal' },
  { key: 'work_schedule', tr: 'Çalışma düzeninizi nasıl tanımlarsınız?', en: 'How would you describe your work schedule?' },
  { key: 'typical_availability', tr: 'Genellikle hangi gün/saatlerde müsaitsiniz?', en: 'What days or times are you usually available?', kind: 'list' },
  { key: 'interests', tr: 'Hangi konular ilginizi çekiyor?', en: 'What topics interest you?', kind: 'list' },
  { key: 'skills_to_develop', tr: 'Hangi becerileri geliştirmek istiyorsunuz?', en: 'Which skills would you like to develop?', kind: 'list' },
  { key: 'planning_preferences', tr: 'Planlamada hangi tercihleri dikkate alalım?', en: 'What planning preferences should we consider?', kind: 'list' },
  { key: 'recommendation_frequency', tr: 'Ne sıklıkta öneri almak istersiniz?', en: 'How often would you like recommendations?', kind: 'frequency' },
];
const labels: Record<string, { tr: string; en: string }> = Object.fromEntries(questions.map(q => [q.key, { tr: q.tr, en: q.en }]));

export function Profile({ token }: { token: string | null }) {
  const [profile, setProfile] = useState<PersonalizationProfile | null>(null);
  const [answer, setAnswer] = useState('');
  const [showReset, setShowReset] = useState(false);
  const [error, setError] = useState('');
  const english = (navigator.language || '').toLowerCase().startsWith('en');
  useEffect(() => { if (token) void getProfile().then(setProfile).catch(() => setError(english ? 'Could not load profile.' : 'Profil yüklenemedi.')); }, [token, english]);
  if (!token) return <section className="card"><h2>{english ? 'Profile' : 'Profil'}</h2><p>{english ? 'Sign in to manage your profile.' : 'Profilinizi yönetmek için giriş yapın.'}</p></section>;
  if (!profile) return <section className="card">{error || '…'}</section>;
  const skipped = profile.onboarding_skipped || [];
  const completed = profile.onboarding_completed || [];
  const known = questions.filter(q => {
    const v = profile[q.key];
    return v !== null && v !== undefined && v !== '' && (!Array.isArray(v) || v.length > 0);
  }).map(q => q.key as string);
  const currentKey = nextOnboardingField(questions.map(q => q.key as OnboardingField), [...completed, ...known as OnboardingField[]], skipped);
  const current = questions.find(q => String(q.key) === currentKey);
  const profileFields = questions.map(q => q.key as string);
  const handleAnswer = async (value: string, key: keyof PersonalizationProfile) => {
    let change: Partial<PersonalizationProfile>;
    if (key === 'deadlines_goals') {
      change = { deadlines_goals: value.trim() ? value.split(',').map(row => { const [title, deadline, kind] = row.split('|').map(item => item.trim()); return { title, deadline: deadline || null, kind: (kind || 'goal') as 'goal' | 'exam' | 'deadline' }; }) : [] };
    } else if (key === 'interests' || key === 'typical_availability' || key === 'skills_to_develop' || key === 'planning_preferences') {
      change = { [key]: value.split(',').map(item => item.trim()).filter(Boolean) };
    } else {
      change = { [key]: value } as Partial<PersonalizationProfile>;
    }
    const saved = await updateProfile({ ...change, ...recordOnboardingAnswer(key as OnboardingField, completed, skipped) });
    setProfile(saved); setAnswer(''); setError('');
  };
  const skip = async () => {
    if (!current) return;
    setProfile(await updateProfile({ onboarding_skipped: recordOnboardingSkip(current.key as OnboardingField, skipped) })); setAnswer('');
  };
  const reset = async () => { await resetProfile(); setProfile(await getProfile()); setShowReset(false); };
  const edit = async (key: string, value: string) => {
    const field = key as keyof PersonalizationProfile;
    if (value.trim() === '') {
      setProfile(await deleteProfileField(key).then(getProfile));
      return;
    }
    if (field === 'deadlines_goals') {
      const saved = await updateProfile({ deadlines_goals: value.split(',').map(row => { const [title, deadline, kind] = row.split('|').map(item => item.trim()); return { title, deadline: deadline || null, kind: (kind || 'goal') as 'goal' | 'exam' | 'deadline' }; }).filter(item => item.title) }); setProfile(saved); return;
    }
    if (['interests', 'typical_availability', 'skills_to_develop', 'planning_preferences'].includes(key)) {
      const saved = await updateProfile({ [field]: value.split(',').map(v => v.trim()).filter(Boolean) } as Partial<PersonalizationProfile>); setProfile(saved); return;
    }
    const saved = await updateProfile({ [field]: value } as Partial<PersonalizationProfile>); setProfile(saved);
  };
  const valueText = (key: string) => {
    const value = profile[key as keyof PersonalizationProfile];
    if (Array.isArray(value)) return key === 'deadlines_goals' ? value.map(item => typeof item === 'string' ? item : `${item.title} | ${item.deadline || ''} | ${item.kind}`).join(', ') : value.join(', ');
    return value == null ? '' : String(value);
  };
  const resetDeletes = english
    ? 'Preferred name; age range; life context; study field and year; goals, exam dates and deadlines; work schedule; typical availability; interests; skills; planning preferences; recommendation frequency; onboarding progress.'
    : 'Tercih edilen isim; yaş aralığı; yaşam bağlamı; eğitim alanı ve yılı; hedefler, sınav tarihleri ve son tarihler; çalışma düzeni; tipik müsaitlik; ilgi alanları; beceriler; planlama tercihleri; öneri sıklığı; başlangıç ilerlemesi.';
  const resetKeeps = english
    ? 'Plans; outcomes; saved suggestions or recommendations; recommendation feedback (if any; the current API stores none); account and authentication.'
    : 'Planlar; sonuçlar; kayıtlı öneriler/tavsiyeler; öneri geri bildirimleri (varsa; mevcut API geri bildirim saklamıyor); hesap ve kimlik doğrulama.';
  return <section className="card">
    <h2>{english ? 'Profile and onboarding' : 'Profil ve başlangıç'}</h2>
    <p>{english ? 'Answers are saved as structured profile data. No conversation transcript is stored.' : 'Yanıtlar yapılandırılmış profil verisi olarak kaydedilir. Konuşma dökümü saklanmaz.'}</p>
    {current ? <div aria-live="polite"><h3>{english ? current.en : current.tr}</h3>
      {(current.kind === 'life' || current.kind === 'frequency' || current.kind === 'age') ? <select aria-label={english ? 'Answer' : 'Yanıt'} value={answer} onChange={e => setAnswer(e.target.value)}><option value="">{english ? 'Choose…' : 'Seçin…'}</option>{(current.kind === 'life' ? [['student', 'Student', 'Öğrenci'], ['working', 'Working', 'Çalışıyor'], ['other', 'Other', 'Diğer']] : current.kind === 'age' ? [['under_18','Under 18','18 yaş altı'],['18_24','18–24','18–24'],['25_34','25–34','25–34'],['35_44','35–44','35–44'],['45_plus','45+','45+'],['prefer_not_to_say','Prefer not to say','Paylaşmak istemiyorum']] : [['daily', 'Daily', 'Günlük'], ['weekly', 'Weekly', 'Haftalık'], ['on_demand', 'On demand', 'İstek üzerine'], ['off', 'Off', 'Kapalı']]).map(([v, en, tr]) => <option key={v} value={v}>{english ? en : tr}</option>)}</select> : <input value={answer} onChange={e => setAnswer(e.target.value)} aria-label={english ? 'Answer' : 'Yanıt'} placeholder={current.kind === 'list' || current.kind === 'goal' ? (english ? 'Separate items with commas' : 'Öğeleri virgülle ayırın') : ''} />}
      <button type="button" disabled={!answer.trim()} onClick={() => void handleAnswer(answer, current.key)}>{english ? 'Save and continue' : 'Kaydet ve devam et'}</button>
      <button type="button" onClick={() => void skip()}>{english ? 'Skip' : 'Geç'}</button></div> : <p>{english ? 'Onboarding is complete. You can edit any answer below.' : 'Başlangıç tamamlandı. Aşağıdan yanıtlarınızı düzenleyebilirsiniz.'}</p>}
    {skipped.length > 0 && <div><h3>{english ? 'Skipped questions' : 'Atlanan sorular'}</h3>{skipped.map(field => { const question = questions.find(q => q.key === field); return question ? <button key={field} type="button" onClick={() => void updateProfile({ onboarding_skipped: skipped.filter(item => item !== field) }).then(setProfile)}>{english ? `Answer: ${question.en}` : `Yanıtla: ${question.tr}`}</button> : null; })}</div>}
    {error && <p role="alert">{error}</p>}
    <h3>{english ? 'Review and edit' : 'Gözden geçir ve düzenle'}</h3>
    <div>{profileFields.map(key => <ProfileFieldEditor key={`${key}-${valueText(key)}`} field={key} label={labels[key]?.[english ? 'en' : 'tr'] || key} value={valueText(key)} english={english} onSave={value => edit(key, value)} onDelete={() => deleteProfileField(key).then(getProfile).then(setProfile)} />)}</div>
    <button type="button" onClick={() => setShowReset(true)}>{english ? 'Reset personalization profile' : 'Kişiselleştirme profilini sıfırla'}</button>
    {showReset && <div role="dialog" aria-modal="true" aria-labelledby="reset-title"><h3 id="reset-title">{english ? 'Reset profile?' : 'Profil sıfırlansın mı?'}</h3><p><strong>{english ? 'Will be deleted:' : 'Silinecek:'}</strong> {resetDeletes}</p><p><strong>{english ? 'Will be kept:' : 'Korunacak:'}</strong> {resetKeeps}</p><button type="button" onClick={() => void reset()}>{english ? 'Confirm reset' : 'Sıfırlamayı onayla'}</button><button type="button" onClick={() => setShowReset(false)}>{english ? 'Cancel' : 'Vazgeç'}</button></div>}
  </section>;
}

function ProfileFieldEditor({ field, label, value, english, onSave, onDelete }: { field: string; label: string; value: string; english: boolean; onSave: (value: string) => Promise<void>; onDelete: () => Promise<void> }) {
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  return <form style={{ display: 'block', margin: '0.5rem 0' }} onSubmit={event => { event.preventDefault(); setBusy(true); void onSave(draft).finally(() => setBusy(false)); }}>
    <label><span>{label}</span>{['life_context', 'age_range', 'recommendation_frequency'].includes(field) ? <select aria-label={label} value={draft} onChange={event => setDraft(event.target.value)}><option value="">{english ? 'Not set' : 'Belirtilmedi'}</option>{(field === 'life_context' ? [['student','Student','Öğrenci'],['working','Working','Çalışıyor'],['other','Other','Diğer']] : field === 'age_range' ? [['under_18','Under 18','18 yaş altı'],['18_24','18–24','18–24'],['25_34','25–34','25–34'],['35_44','35–44','35–44'],['45_plus','45+','45+'],['prefer_not_to_say','Prefer not to say','Paylaşmak istemiyorum']] : [['daily','Daily','Günlük'],['weekly','Weekly','Haftalık'],['on_demand','On demand','İstek üzerine'],['off','Off','Kapalı']]).map(([v,en,tr]) => <option key={v} value={v}>{english ? en : tr}</option>)}</select> : <input aria-label={label} value={draft} onChange={event => setDraft(event.target.value)} />}</label>
    <button type="submit" disabled={busy}>{english ? 'Save' : 'Kaydet'}</button>
    {value && <button type="button" disabled={busy} onClick={() => { setBusy(true); void onDelete().finally(() => setBusy(false)); }}>{english ? 'Delete answer' : 'Yanıtı sil'}</button>}
  </form>;
}
