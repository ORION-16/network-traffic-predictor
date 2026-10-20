import React from 'react';

/**
 * ErrorAlert — renders prominent actionable alert banners for errors,
 * specifically highlighting permission-denied errors and how to resolve them.
 */
export default function ErrorAlert({ error, onDismiss }) {
  if (!error) return null;

  const isPermission =
    error.toLowerCase().includes('permission') ||
    error.toLowerCase().includes('privilege') ||
    error.toLowerCase().includes('operation not permitted');

  return (
    <div
      role="alert"
      id="capture-error-alert"
      className="rounded-2xl p-4 bg-rose-500/10 border border-rose-500/30 text-rose-200 mb-6 transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-rose-500/20 text-rose-400 mt-0.5">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div>
            <h4 className="text-sm font-bold text-white flex items-center gap-2">
              {isPermission ? 'Elevated Permissions Required' : 'Capture Error Encountered'}
            </h4>
            <p className="text-xs text-rose-300/90 mt-1 leading-relaxed">{error}</p>

            {isPermission && (
              <div className="mt-3 p-3 rounded-xl bg-slate-950/80 border border-rose-500/20 text-xs font-mono text-slate-300">
                <p className="text-[11px] font-sans font-semibold text-rose-300 mb-1.5">
                  Actionable fix: Raw socket capture requires elevated privileges on your OS:
                </p>
                <div className="space-y-1 text-emerald-400">
                  <p>
                    <span className="text-slate-500"># macOS:</span> sudo python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
                  </p>
                  <p>
                    <span className="text-slate-500"># Linux:</span> sudo setcap cap_net_raw,cap_net_admin+eip $(which python3)
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-rose-400 hover:text-white p-1 rounded-lg hover:bg-rose-500/20 transition-colors"
            title="Dismiss error"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
