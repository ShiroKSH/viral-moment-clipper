import { RefreshCw, Square } from 'lucide-react';
import type { JobRecord } from '../types';

type Props = {
  job: JobRecord | null;
  cancelling: boolean;
  onCancel: () => void;
};

export default function ProgressView({ job, cancelling, onCancel }: Props) {
  const active = job?.status === 'queued' || job?.status === 'running';
  const cancelPending = cancelling || Boolean(job?.cancel_requested);
  const progressPercent = Math.round((job?.progress || 0) * 100);

  return (
    <section className="panel progress-panel">
      <div className="panel-title">
        <h2>Progress</h2>
        <div className="progress-actions">
          {active ? (
            <RefreshCw className="spin" size={16} aria-hidden="true" />
          ) : (
            <span className="status-pill">{job?.status || 'idle'}</span>
          )}
          {active ? (
            <button
              className="icon-button compact danger"
              type="button"
              disabled={cancelPending}
              onClick={onCancel}
            >
              <Square size={13} aria-hidden="true" /> {cancelPending ? 'Cancelling…' : 'Cancel'}
            </button>
          ) : null}
        </div>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Job progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progressPercent}
      >
        <div style={{ width: `${progressPercent}%` }} />
      </div>
      <div className="stage-line">
        <strong>{job?.stage || 'idle'}</strong>
        <span>{job?.message || 'Ready'}</span>
      </div>
      {job?.error ? <div className="error-box">{job.error}</div> : null}
      <div className="log-box">
        {(job?.logs || []).slice(-6).map((line, index) => (
          <div key={`${line}-${index}`}>{line}</div>
        ))}
      </div>
    </section>
  );
}
