import { create } from 'zustand';
import client from '../api/client';

const useProfileStore = create((set) => ({
  profiles: [],
  loading: false,

  fetchProfiles: async () => {
    set({ loading: true });
    try {
      const { data } = await client.get('/profiles');
      set({ profiles: data });
    } finally {
      set({ loading: false });
    }
  },

  createProfile: async (payload) => {
    const { data } = await client.post('/profiles', payload);
    set((state) => ({ profiles: [data, ...state.profiles] }));
    return data;
  },

  updateProfile: async (id, payload) => {
    const { data } = await client.put(`/profiles/${id}`, payload);
    set((state) => ({
      profiles: state.profiles.map((p) => (p.id === id ? data : p)),
    }));
    return data;
  },

  deleteProfile: async (id) => {
    await client.delete(`/profiles/${id}`);
    set((state) => ({ profiles: state.profiles.filter((p) => p.id !== id) }));
  },
}));

export default useProfileStore;
