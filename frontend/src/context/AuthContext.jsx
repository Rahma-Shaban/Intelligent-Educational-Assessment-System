import React, { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, register as apiRegister, getMe } from '../api/client';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(() => {
    try {
      const savedUser = localStorage.getItem('user');
      return savedUser ? JSON.parse(savedUser) : null;
    } catch {
      return null;
    }
  });
  const [token, setToken] = useState(() => localStorage.getItem('token') || null);
  const [loading, setLoading] = useState(true);

  // Restore session on mount
  useEffect(() => {
    const initAuth = async () => {
      const savedToken = localStorage.getItem('token');
      if (savedToken) {
        try {
          const userData = await getMe();
          setUser(userData);
          localStorage.setItem('user', JSON.stringify(userData));
        } catch (err) {
          console.error('Session restoration failed:', err);
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          setToken(null);
          setUser(null);
        }
      }
      setLoading(false);
    };

    initAuth();
  }, []);

  const login = async (email, password) => {
    const data = await apiLogin(email, password);
    const jwtToken = data.access_token || data.token;
    if (jwtToken) {
      localStorage.setItem('token', jwtToken);
      setToken(jwtToken);
    }

    let currentUser = data.user;
    if (!currentUser) {
      try {
        currentUser = await getMe();
      } catch {
        // Fallback if getMe is not yet implemented or returns error
        currentUser = {
          email,
          name: data.name || email.split('@')[0],
          role: data.role || 'student',
          id: data.id || data.user_id,
        };
      }
    }

    localStorage.setItem('user', JSON.stringify(currentUser));
    setUser(currentUser);
    return currentUser;
  };

  const register = async (name, email, password, role) => {
    const data = await apiRegister(name, email, password, role);
    // If registration returns tokens directly, auto login
    const jwtToken = data.access_token || data.token;
    if (jwtToken) {
      localStorage.setItem('token', jwtToken);
      setToken(jwtToken);
      const currentUser = data.user || {
        name,
        email,
        role,
        id: data.id || data.user_id,
      };
      localStorage.setItem('user', JSON.stringify(currentUser));
      setUser(currentUser);
      return currentUser;
    } else {
      // Otherwise login with credentials
      return await login(email, password);
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setToken(null);
    setUser(null);
  };

  const updateUser = (updated) => {
    setUser(updated);
    localStorage.setItem('user', JSON.stringify(updated));
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        register,
        logout,
        updateUser,
        isAuthenticated: !!token && !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
