import React, { useState, useRef, useEffect, useCallback } from 'react';
import { MessageCircle, X, Send, Loader2, AlertCircle, MinusCircle, RotateCcw, BookOpen } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useAuth } from '../context/AuthContext';
import { sendChatMessage } from '../api/client';

const ChatBot = () => {
  const { user, isAuthenticated } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const isSubmittingRef = useRef(false);
  const abortControllerRef = useRef(null);
  const isMountedRef = useRef(true);

  // Mount tracking
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Language detection
  const isArabic = (text) => {
    if (!text) return false;
    const arabicChars = (text.match(/[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/g) || []).length;
    return arabicChars > text.length * 0.25;
  };

  const getDirection = (text) => (isArabic(text) ? 'rtl' : 'ltr');

  // Scroll to bottom when messages change or loading starts
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen && !isMinimized && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen, isMinimized]);

  // Initialize with welcome message on first open
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      const userName = user?.name?.split(' ')[0] || '';
      setMessages([
        {
          role: 'assistant',
          content: `مرحباً ${userName}! 👋\n\nأنا **مساعدك الأكاديمي الذكي** في منصة التقييم التعليمي.\n\nيمكنك سؤالي عن:\n- 📚 **مفاهيم المنهج الدراسي** وشرح الدروس والأكواد البرمجية\n- 📝 **امتحاناتك المنشورة** ودرجاتك ونتائجك السابقة\n- 🧭 **كيفية استخدام المنصة** واختيار الدكتور أو بدء الامتحان\n\nاكتب سؤالك بالعربية أو بالإنجليزية وسأساعدك فوراً!\n\n---\n*Hello ${userName}! Ask me any questions about your curriculum, exams, or navigating the platform.*`,
          sources: [],
        },
      ]);
    }
  }, [isOpen, messages.length, user]);

  const handleOpen = () => {
    setIsOpen(true);
    setIsMinimized(false);
  };

  const handleClose = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsLoading(false);
    isSubmittingRef.current = false;
    setIsOpen(false);
    setIsMinimized(false);
  };

  const handleMinimize = () => {
    setIsMinimized(true);
  };

  const executeSend = useCallback(async (textToSend) => {
    const trimmed = (textToSend || '').trim();
    if (!trimmed || isSubmittingRef.current) return;

    if (trimmed.length > 2000) {
      setError('الرسالة طويلة جداً. الحد الأقصى 2000 حرف. / Message too long. Max 2000 characters.');
      return;
    }

    isSubmittingRef.current = true;
    setIsLoading(true);
    setError(null);

    // Append user message immediately
    const userMessage = { role: 'user', content: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');

    // Cancel any ongoing request before creating a new one
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      // Build conversation history (skip system/welcome, limit to last 8 turns)
      const history = messages
        .filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.isError))
        .slice(-8)
        .map((m) => ({ role: m.role, content: m.content }));

      const response = await sendChatMessage(
        {
          message: trimmed,
          conversation_history: history,
          language: 'auto',
        },
        { signal: controller.signal }
      );

      if (!isMountedRef.current) return;

      const reply = response?.reply || 'عذراً، لم أتمكن من الحصول على إجابة. / Sorry, could not generate a response.';
      const sources = response?.sources || [];

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: reply,
          sources: sources,
          language: response?.language || 'auto',
        },
      ]);
    } catch (err) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
        // Request cancelled intentionally
        return;
      }
      if (!isMountedRef.current) return;

      console.error('Chatbot error:', err);
      const status = err.response?.status;
      let errorMsg;
      if (status === 401) {
        errorMsg = 'انتهت الجلسة. يرجى تسجيل الدخول مجدداً. / Session expired. Please log in again.';
      } else if (status === 403) {
        errorMsg = 'هذه الخدمة متاحة للطلاب فقط. / This service is available for students only.';
      } else if (status === 422) {
        errorMsg = 'الرسالة غير صالحة. يرجى المحاولة مرة أخرى. / Invalid message. Please try again.';
      } else if (status === 504 || err.code === 'ECONNABORTED') {
        errorMsg = 'استغرقت الاستجابة وقتاً أطول من المتوقع. يرجى إعادة المحاولة. / Request timed out. Please try again.';
      } else if (status === 502 || status === 503) {
        errorMsg = 'خدمة الذكاء الاصطناعي غير متاحة حالياً. يرجى المحاولة بعد قليل. / AI service temporarily unavailable. Please retry in a moment.';
      } else {
        errorMsg = err.response?.data?.detail || 'حدث خطأ في الاتصال بالخدمة. يرجى إعادة المحاولة. / Service connection error. Please try again.';
      }

      setError(errorMsg);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `⚠️ ${errorMsg}`,
          isError: true,
          failedText: trimmed,
        },
      ]);
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
        isSubmittingRef.current = false;
        abortControllerRef.current = null;
      }
    }
  }, [messages]);

  const handleSend = () => {
    executeSend(input);
  };

  const handleRetry = (failedText) => {
    executeSend(failedText);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Only show for authenticated students
  if (!isAuthenticated || !user || user.role !== 'student') {
    return null;
  }

  // Floating button launcher
  if (!isOpen) {
    return (
      <button
        onClick={handleOpen}
        className="fixed bottom-6 left-6 z-50 w-14 h-14 bg-gradient-to-br from-clay-600 to-clay-800 text-white rounded-full shadow-pop hover:shadow-warm hover:scale-105 active:scale-95 transition-all duration-200 flex items-center justify-center group"
        aria-label="فتح المساعد الذكي / Open Chatbot"
        title="المساعد الذكي / Smart Assistant"
      >
        <MessageCircle className="w-6 h-6 group-hover:scale-110 transition-transform" />
        <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-gold-400 rounded-full border-2 border-white animate-pulse" />
      </button>
    );
  }

  // Minimized pill state
  if (isMinimized) {
    return (
      <div className="fixed bottom-6 left-6 z-50 flex items-center gap-2">
        <button
          onClick={() => setIsMinimized(false)}
          className="px-4 py-2.5 bg-gradient-to-br from-clay-600 to-clay-800 text-white rounded-full shadow-pop hover:shadow-warm transition-all flex items-center gap-2 text-sm font-bold"
        >
          <MessageCircle className="w-4 h-4" />
          <span>المساعد الذكي / AI Tutor</span>
        </button>
        <button
          onClick={handleClose}
          className="w-8 h-8 bg-cocoa-100 text-cocoa-600 rounded-full flex items-center justify-center hover:bg-rose-100 hover:text-rose-600 transition-colors"
          aria-label="إغلاق / Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    );
  }

  // Full chat panel
  return (
    <div className="fixed bottom-4 left-4 right-4 sm:right-auto sm:w-[400px] sm:max-w-md h-[540px] max-h-[calc(100vh-2rem)] bg-paper border border-sand rounded-2xl shadow-pop flex flex-col overflow-hidden z-50">
      {/* Header */}
      <div className="bg-gradient-to-l from-cocoa-950 to-cocoa-900 px-4 py-3 flex items-center justify-between shrink-0 select-none">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-gradient-to-br from-gold-400 to-gold-500 text-cocoa-950 rounded-xl flex items-center justify-center font-code font-bold text-xs shadow-sm">
            AI
          </div>
          <div>
            <h3 className="text-sm font-bold text-white leading-tight">المساعد الأكاديمي الذكي</h3>
            <p className="text-[10px] text-cocoa-300">Intelligent Academic Tutor</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleMinimize}
            className="p-1.5 text-cocoa-300 hover:text-gold-400 hover:bg-white/10 rounded-lg transition-colors"
            aria-label="تصغير / Minimize"
            title="تصغير"
          >
            <MinusCircle className="w-4 h-4" />
          </button>
          <button
            onClick={handleClose}
            className="p-1.5 text-cocoa-300 hover:text-rose-400 hover:bg-white/10 rounded-lg transition-colors"
            aria-label="إغلاق / Close"
            title="إغلاق"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3.5 bg-cream/40">
        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          const dir = getDirection(msg.content);

          return (
            <div
              key={idx}
              className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}
            >
              <div
                dir={dir}
                className={`max-w-[88%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed break-words shadow-sm ${
                  isUser
                    ? 'bg-gradient-to-l from-clay-600 to-clay-700 text-white rounded-br-sm'
                    : msg.isError
                    ? 'bg-rose-50 text-rose-800 border border-rose-200 rounded-bl-sm'
                    : 'bg-white text-ink border border-sand rounded-bl-sm'
                }`}
              >
                {/* Message body with Markdown rendering */}
                {isUser ? (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <div className="prose prose-sm max-w-none text-current">
                    <ReactMarkdown
                      components={{
                        p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
                        ul: ({ node, ...props }) => <ul className="list-disc list-inside mb-2 space-y-1" {...props} />,
                        ol: ({ node, ...props }) => <ol className="list-decimal list-inside mb-2 space-y-1" {...props} />,
                        li: ({ node, ...props }) => <li className="leading-relaxed" {...props} />,
                        code: ({ node, inline, ...props }) =>
                          inline ? (
                            <code className="bg-sand/60 px-1 py-0.5 rounded font-code text-xs text-clay-700" {...props} />
                          ) : (
                            <pre className="bg-cocoa-950 text-sand p-2.5 rounded-lg font-code text-xs overflow-x-auto my-2">
                              <code {...props} />
                            </pre>
                          ),
                        strong: ({ node, ...props }) => <strong className="font-bold text-inherit" {...props} />,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}

                {/* Sources & Citations */}
                {!isUser && msg.sources && msg.sources.length > 0 && (
                  <div className="mt-2.5 pt-2 border-t border-sand/60">
                    <div className="flex items-center gap-1.5 text-[11px] font-bold text-clay-700 mb-1">
                      <BookOpen className="w-3 h-3 text-clay-600" />
                      <span>المصادر المرجعية / References:</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {msg.sources.map((src, sIdx) => (
                        <span
                          key={sIdx}
                          className="inline-block text-[10px] bg-sand/50 text-cocoa-700 px-2 py-0.5 rounded border border-sand/80 font-medium"
                          title={`Chunk ID: ${src.chunk_id}`}
                        >
                          {src.lesson_title || `Lesson ${src.lesson_id}`}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Retry action for failed messages */}
                {msg.isError && msg.failedText && (
                  <div className="mt-2 pt-1.5 flex justify-end">
                    <button
                      onClick={() => handleRetry(msg.failedText)}
                      disabled={isLoading}
                      className="inline-flex items-center gap-1 text-xs font-bold text-rose-600 hover:text-rose-800 disabled:opacity-50 transition-colors py-1 px-2 rounded-md hover:bg-rose-100/60"
                    >
                      <RotateCcw className="w-3 h-3" />
                      <span>إعادة المحاولة / Retry</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Loading Indicator */}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white text-cocoa-600 border border-sand rounded-2xl rounded-bl-sm px-4 py-2.5 shadow-sm flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-clay-500" />
              <span className="text-xs font-medium">جاري التفكير وصياغة الإجابة... / Thinking...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Error Notification */}
      {error && (
        <div dir={getDirection(error)} className="px-3 py-2 bg-rose-50 border-t border-rose-200 flex items-start gap-2 shrink-0">
          <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
          <p className="text-xs text-rose-700 leading-relaxed flex-1">{error}</p>
          <button
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-rose-600 shrink-0"
            aria-label="تجاهل الخطأ"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Input Form */}
      <div className="px-3 py-2.5 bg-paper border-t border-sand shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="اكتب سؤالك هنا... / Type your question..."
            disabled={isLoading}
            rows={1}
            dir="auto"
            className="flex-1 resize-none rounded-xl border border-cocoa-200 bg-cream/40 px-3 py-2 text-sm text-ink placeholder:text-cocoa-400 focus:outline-none focus:ring-2 focus:ring-clay-500/30 focus:border-clay-500 disabled:opacity-50 transition-all max-h-24 overflow-y-auto"
            style={{ minHeight: '38px' }}
            onInput={(e) => {
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 96) + 'px';
            }}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="w-10 h-10 bg-gradient-to-br from-clay-600 to-clay-700 text-white rounded-xl flex items-center justify-center hover:from-clay-500 hover:to-clay-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all shrink-0 shadow-sm active:scale-95"
            aria-label="إرسال / Send"
            title="إرسال"
          >
            <Send className="w-4 h-4 rtl:rotate-180" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatBot;
