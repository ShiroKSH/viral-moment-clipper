import { Check, X } from 'lucide-react';
import type { ClipCandidate } from '../types';
import ClipEditor from './ClipEditor';

type Props = {
  clip: ClipCandidate;
  onPatch: (clipId: string, patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) => void;
  onAccept: (clipId: string) => void;
  onReject: (clipId: string) => void;
};

export default function ClipCard({ clip, onPatch, onAccept, onReject }: Props) {
  const accepted = clip.review_action === 'accept';
  const rejected = clip.review_action === 'reject';
  return (
    <article className="clip-card">
      <header className="clip-head">
        <label className="select-clip">
          <input type="checkbox" checked={clip.selected} onChange={(event) => onPatch(clip.id, { selected: event.target.checked })} />
          <span>{clip.id}</span>
        </label>
        <div className="score-stack">
          <strong>{Math.round(clip.final_score)}</strong>
          <span>{clip.moment_type}</span>
        </div>
      </header>
      <div className="score-row">
        <span>base {Math.round(clip.base_score)}</span>
        <span>personal {Math.round(clip.personal_score)}</span>
        <span>{clip.duration.toFixed(1)}s</span>
        {clip.speaker_count > 1 ? <span className="feedback-pill edited">{clip.speaker_count} speakers · {clip.speaker_switches} turns</span> : null}
        {clip.review_action ? <span className={`feedback-pill ${clip.review_action}`}>{clip.review_action}</span> : null}
        {clip.latest_feedback_action && clip.latest_feedback_action !== clip.review_action && clip.latest_feedback_action !== 'rendered' ? (
          <span className={`feedback-pill ${clip.latest_feedback_action}`}>{clip.latest_feedback_action}</span>
        ) : null}
        {clip.rendered ? <span className="rendered-pill">rendered</span> : null}
      </div>
      <h3>{clip.hook_text}</h3>
      <p>{clip.summary}</p>
      <ClipEditor clip={clip} onPatch={(patch) => onPatch(clip.id, patch)} />
      <details>
        <summary>Reason</summary>
        <p>{clip.reason}</p>
        {clip.problems.length ? <p className="problem-text">{clip.problems.join(', ')}</p> : null}
        <p className="transcript-text">{clip.text}</p>
      </details>
      <footer className="clip-actions">
        <button type="button" className="icon-button" disabled={accepted} onClick={() => onAccept(clip.id)} aria-label={`Accept ${clip.id}`}>
          <Check size={16} /> {accepted ? 'Accepted' : 'Accept'}
        </button>
        <button type="button" className="icon-button secondary" disabled={rejected} onClick={() => onReject(clip.id)} aria-label={`Reject ${clip.id}`}>
          <X size={16} /> {rejected ? 'Rejected' : 'Reject'}
        </button>
      </footer>
    </article>
  );
}
