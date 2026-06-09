import axios from 'axios';
import toast from 'react-hot-toast';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const client = axios.create({ baseURL: API_URL });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  async (err) => {
    const config = err.config;

    // Retry GET requests on 5xx (transient server errors / cold starts)
    if (
      config &&
      config.method === 'get' &&
      err.response?.status >= 500 &&
      (config._retryCount || 0) < 2
    ) {
      config._retryCount = (config._retryCount || 0) + 1;
      await new Promise((r) => setTimeout(r, 1000 * config._retryCount));
      return client(config);
    }

    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    if (err.response?.status === 429) {
      const d = err.response.data?.detail || {};
      toast.error(
        `${d.upgrade_message || 'Daily limit reached. Upgrade your plan.'}`,
        { duration: 5000 }
      );
    }
    return Promise.reject(err);
  }
);

export default client;

/**
 * Authenticated file download.
 *
 * Cloud (prod): backend returns { url, filename } — a SAS URL pointing at blob
 * storage. We navigate directly to it; the browser downloads without CORS issues
 * because navigation bypasses the same-origin restriction.
 *
 * Local dev: backend returns a FileResponse (binary). We read it as a blob and
 * trigger save-as.
 */
export async function downloadFile(path, fallbackFilename = 'download') {
  const response = await client.get(path, { responseType: 'blob' });

  // If the response is JSON (Content-Type application/json) it's a SAS redirect object
  const contentType = response.headers?.['content-type'] || '';
  if (contentType.includes('application/json')) {
    const text = await response.data.text();
    const { url, filename } = JSON.parse(text);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || fallbackFilename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }

  // Local dev — binary blob from FileResponse
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const a = document.createElement('a');
  a.href = url;
  a.download = fallbackFilename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
