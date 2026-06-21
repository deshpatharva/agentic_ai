import { create } from 'zustand';
import client from '../api/client';

// Tolerate a missing/corrupt 'user' entry (e.g. the literal string "undefined"
// left by a past bad write). A throw here runs at module load and would
// white-screen the entire app with no way to recover.
function readStoredUser() {
  try {
    const raw = localStorage.getItem('user');
    return raw ? JSON.parse(raw) : null;
  } catch {
    localStorage.removeItem('user');
    return null;
  }
}

function persistUser(user) {
  if (user === undefined || user === null) localStorage.removeItem('user');
  else localStorage.setItem('user', JSON.stringify(user));
}

const useAuthStore = create((set) => ({
  user:  readStoredUser(),
  token: localStorage.getItem('token') || null,

  login: (token, user) => {
    localStorage.setItem('token', token);
    persistUser(user);
    set({ token, user: user ?? null });
  },

  logout: () => {
    // Clear locally first, then revoke server-side (token blocklist) with the
    // captured token — fire and forget.
    const token = localStorage.getItem('token');
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    set({ token: null, user: null });
    if (token) {
      client.post('/auth/logout', null, { headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    }
  },

  fetchMe: async () => {
    try {
      const { data } = await client.get('/auth/me');
      persistUser(data);
      set({ user: data ?? null });
    } catch {
      // token expired
    }
  },
}));

export default useAuthStore;
