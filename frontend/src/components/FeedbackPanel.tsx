import type { LearningSummary } from '../types';

type Props = {
  learning: LearningSummary | null;
  transcriptPreview: string;
  speakerSummary?: string;
};

export default function FeedbackPanel({ learning, transcriptPreview, speakerSummary }: Props) {
  return (
    <section className="panel learning-panel">
      <div className="panel-title">
        <h2>Learning</h2>
        <span className="status-pill">{learning?.active_ranker_version || 'online_preference_v001'}</span>
      </div>
      <div className="learning-grid">
        <div>
          <strong>{learning?.total_clips_analyzed ?? 0}</strong>
          <span>clips</span>
        </div>
        <div>
          <strong>{learning?.accepted_count ?? 0}</strong>
          <span>accepted</span>
        </div>
        <div>
          <strong>{learning?.rejected_count ?? 0}</strong>
          <span>rejected</span>
        </div>
        <div>
          <strong>{Math.round(learning?.average_score_accepted ?? 0)}</strong>
          <span>avg accepted</span>
        </div>
        <div>
          <strong>{learning?.training_rows ?? 0}</strong>
          <span>training rows</span>
        </div>
        <div>
          <strong>{learning?.positive_count ?? 0}/{learning?.negative_count ?? 0}</strong>
          <span>{learning?.model_active ? 'model active' : learning?.training_ready ? 'ready to train' : 'collecting signals'}</span>
        </div>
        <div>
          <strong>{Math.round(learning?.retention?.average_retention_percent ?? 0)}%</strong>
          <span>avg retention</span>
        </div>
      </div>
      {speakerSummary ? <p className="path-line">{speakerSummary}</p> : null}
      <div className="type-row">
        {(learning?.top_moment_types || []).map((item) => (
          <span key={item.moment_type}>{item.moment_type} {item.count}</span>
        ))}
      </div>
      <textarea readOnly value={transcriptPreview} placeholder="Transcript preview" />
    </section>
  );
}
