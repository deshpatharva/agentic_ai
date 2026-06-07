import useAuthStore from '../store/authStore';

export default function TrialBanner() {
  const { user } = useAuthStore();
  if (!user?.trial_expires_at) return null;

  const expires = new Date(user.trial_expires_at);
  const daysLeft = Math.ceil((expires - Date.now()) / 86_400_000);
  if (daysLeft <= 0) return null;

  return (
    <div className="mx-3 mb-2 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 text-xs text-amber-400">
      <span className="font-semibold">Pro Trial</span>
      {' — '}{daysLeft} day{daysLeft !== 1 ? 's' : ''} left
    </div>
  );
}
