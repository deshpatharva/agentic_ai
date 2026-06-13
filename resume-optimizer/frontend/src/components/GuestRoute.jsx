import { Navigate } from 'react-router-dom';
import useAuthStore from '../store/authStore';

export default function GuestRoute({ children }) {
  const { token } = useAuthStore();
  if (token) return <Navigate to="/optimize" replace />;
  return children;
}
