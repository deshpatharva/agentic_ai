import client from './client';

export const listSessions  = ()          => client.get('/optimize/sessions');
export const getSession    = (id)        => client.get(`/optimize/sessions/${id}`);
export const renameSession = (id, title) => client.patch(`/optimize/sessions/${id}`, { title });
export const deleteSession = (id)        => client.delete(`/optimize/sessions/${id}`);
