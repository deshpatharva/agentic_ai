import useAuthStore from '../store/authStore';

/* Lives inside the always-ink sidebar, so colors are fixed like the sidebar's. */
export default function TrialBanner() {
  const { user } = useAuthStore();
  if (!user?.trial_expires_at) return null;

  const expires = new Date(user.trial_expires_at);
  const daysLeft = Math.ceil((expires - Date.now()) / 86_400_000);
  if (daysLeft <= 0) return null;

  return (
    <div className="mb-3 bg-[#EAB308]/10 border border-[#EAB308]/30 rounded-lg px-3 py-2 text-xs text-[#EAB308]">
      <span className="font-semibold">Pro Trial</span>
      {' — '}{daysLeft} day{daysLeft !== 1 ? 's' : ''} left
    </div>
  );
}
