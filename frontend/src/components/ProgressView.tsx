import { RefreshCw } from 'lucide-react';
import type { JobRecord } from '../types';

type Props = {
  job: JobRecord | null;
};

export default function ProgressView({ job }: Props) {
  return (
    <section className="panel progress-panel">
      <div className="panel-title">
        <h2>Progress</h2>
        {job?.status === 'running' ? <RefreshCw className="spin" size={16} aria-hidden="true" /> : <span className="status-pill">{job?.status || 'idle'}</span>}
      </div>
      <div className="progress-track" aria-label="Job progress">
        <div style={{ width: `${Math.round((job?.progress || 0) * 100)}%` }} />
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
