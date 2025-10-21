import axios from 'axios';

const API_BASE_URL = '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 1800000, // 30 minutes for transcription (large files with large model)
});

// Request interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

export const uploadFile = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await api.post('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  
  return response.data;
};

export const transcribeFile = async (fileData) => {
  const response = await api.post('/transcribe', fileData);
  return response.data;
};

export const summarizeTranscription = async (transcriptionId, transcriptionText) => {
  const response = await api.post('/summarize', {
    transcription_id: transcriptionId,
    transcription_text: transcriptionText,
  });
  return response.data;
};

export const getTranscriptions = async (page = 1, perPage = 10, search = '') => {
  const response = await api.get('/transcriptions', {
    params: { page, per_page: perPage, search },
  });
  return response.data;
};

export const getTranscription = async (id) => {
  const response = await api.get(`/transcriptions/${id}`);
  return response.data;
};

export const deleteTranscription = async (id) => {
  const response = await api.delete(`/transcriptions/${id}`);
  return response.data;
};

export default api;
