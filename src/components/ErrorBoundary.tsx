import { Component } from 'react';
import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public render() {
    if (this.state.hasError) {
      return (
        <main className="flex min-h-[240px] items-center justify-center bg-gray-50 px-5 py-10" role="alert">
          <section className="w-full max-w-md rounded-lg border border-red-200 bg-white p-6 text-center shadow-sm">
            <h1 className="text-lg font-semibold text-gray-900">页面暂时无法加载</h1>
            <p className="mt-2 text-sm text-gray-500">请重新加载页面后再试。</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-5 inline-flex h-9 items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
            >
              重新加载
            </button>
            {import.meta.env.DEV && this.state.error?.message && (
              <p className="mt-4 break-words text-left text-xs text-gray-400">{this.state.error.message}</p>
            )}
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
