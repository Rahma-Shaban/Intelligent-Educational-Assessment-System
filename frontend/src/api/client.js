import axios from 'axios';

const API_BASE_URL = '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor: attach JWT from localStorage
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: on 401 clear token and redirect to /login
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      const currentPath = window.location.pathname;
      if (!currentPath.includes('/login') && !currentPath.includes('/register')) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Auth endpoints
export const login = async (email, password) => {
  const response = await apiClient.post('/auth/login', { email, password });
  return response.data;
};

export const register = async (name, email, password, role) => {
  const response = await apiClient.post('/auth/register', {
    name,
    email,
    password,
    role,
  });
  return response.data;
};

export const getMe = async () => {
  const response = await apiClient.get('/auth/me');
  return response.data;
};

export const getProfessors = async () => {
  const response = await apiClient.get('/auth/professors');
  return response.data;
};

export const selectProfessor = async (professorId) => {
  const response = await apiClient.put('/auth/select-professor', {
    professor_id: professorId,
  });
  return response.data;
};

// Curriculum endpoints
export const uploadCurriculum = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await apiClient.post('/curriculum/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const getDocuments = async () => {
  const response = await apiClient.get('/curriculum');
  return response.data;
};

export const getDocumentLessons = async (curriculumId) => {
  const response = await apiClient.get(`/curriculum/${curriculumId}/lessons`);
  return response.data;
};

export const getLessons = async () => {
  const response = await apiClient.get('/curriculum/lessons');
  return response.data;
};

// Exam endpoints
export const generateExam = async (data) => {
  const response = await apiClient.post('/exams/generate', data);
  return response.data;
};

export const getExams = async () => {
  const response = await apiClient.get('/exams');
  return response.data;
};

export const getExam = async (id) => {
  const response = await apiClient.get(`/exams/${id}`);
  return response.data;
};

export const togglePublishExam = async (id, isPublished = true) => {
  const response = await apiClient.patch(`/exams/${id}/publish`, { is_published: isPublished });
  return response.data;
};

export const updateExamQuestion = async (examId, questionIndex, payload) => {
  const response = await apiClient.patch(
    `/exams/${examId}/questions/${questionIndex}`,
    payload
  );
  return response.data;
};

// Attempts endpoints
export const startAttempt = async (examId) => {
  const response = await apiClient.post('/attempts/start', { exam_id: examId });
  return response.data;
};

export const submitAttempt = async (data) => {
  const response = await apiClient.post('/attempts/submit', data);
  return response.data;
};

export const getAttempt = async (id) => {
  const response = await apiClient.get(`/attempts/${id}`);
  return response.data;
};

export const getMyAttempts = async () => {
  const response = await apiClient.get('/attempts/my/history');
  return response.data;
};

// Analytics endpoints
export const runClustering = async () => {
  const response = await apiClient.post('/analytics/cluster');
  return response.data;
};

export const getStudentDashboard = async (studentId) => {
  const path = studentId ? `/analytics/dashboard/student/${studentId}` : '/analytics/dashboard/student';
  const response = await apiClient.get(path);
  return response.data;
};

export const getProfessorDashboard = async () => {
  const response = await apiClient.get('/analytics/dashboard/professor');
  return response.data;
};

// Chatbot endpoint with configurable options (e.g. timeout, abort signal)
export const sendChatMessage = async (data, config = {}) => {
  const response = await apiClient.post('/chatbot/message', data, {
    timeout: 30000,
    ...config,
  });
  return response.data;
};

export default apiClient;
