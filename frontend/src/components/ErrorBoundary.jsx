import React from 'react';
import Button from './ui/Button';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught error:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-cream p-4">
          <div className="max-w-md w-full bg-paper rounded-2xl shadow-warm border border-cocoa-300/40 p-6 text-center space-y-4">
            <div className="w-12 h-12 rounded-2xl rounded-br-sm bg-rose-100 text-rose-600 flex items-center justify-center mx-auto text-xl font-bold -rotate-3">
              !
            </div>
            <h2 className="text-xl font-extrabold text-ink">حصلت مشكلة غير متوقعة</h2>
            <p className="text-sm text-cocoa-500 leading-relaxed">
              حصل خطأ وهو بنعرض الصفحة دي. تقدر ترجع للصفحة اللي فاتت أو للوحة التحكم.
            </p>
            <div className="flex justify-center gap-3 pt-2">
              <Button variant="secondary" onClick={() => window.history.back()}>
                رجوع
              </Button>
              <Button variant="primary" onClick={this.handleReset} className="btn-cut">
                ارجع للرئيسية
              </Button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
