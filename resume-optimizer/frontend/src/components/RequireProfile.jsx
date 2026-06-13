import { Navigate } from 'react-router-dom';
import useAuthStore from '../store/authStore';

/**
 * Blocks access to routes that require at least one complete profile.
 * Redirects to /profiles/new if the user has no usable profile yet.
 * Falls back gracefully when profile_status is absent (older sessions).
 */
export default function RequireProfile({ children }) {
  const user = useAuthStore((s) => s.user);

  if (!user) return <Navigate to="/login" replace />;

  if (user.profile_status === 'incomplete') {
    return <Navigate to="/profiles/new" replace />;
  }

  return children;
}
