import { create } from 'zustand';
import client from '../api/client';

const useAuthStore = create((set) => ({
  user:  JSON.parse(localStorage.getItem('user') || 'null'),
  token: localStorage.getItem('token') || null,

  login: (token, user) => {
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify(user));
    set({ token, user });
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
      localStorage.setItem('user', JSON.stringify(data));
      set({ user: data });
    } catch {
      // token expired
    }
  },
}));

export default useAuthStore;
