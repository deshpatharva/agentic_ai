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
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    set({ token: null, user: null });
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
