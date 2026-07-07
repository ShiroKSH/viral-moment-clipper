import { Scissors } from 'lucide-react';
import type { ClipCandidate } from '../types';
import ClipCard from './ClipCard';

type Props = {
  clips: ClipCandidate[];
  onPatch: (clipId: string, patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) => void;
  onAccept: (clipId: string) => void;
  onReject: (clipId: string) => void;
  onRender: () => void;
};

export default function ClipCandidates({ clips, onPatch, onAccept, onReject, onRender }: Props) {
  const selectedCount = clips.filter((clip) => clip.selected).length;
  return (
    <section className="panel candidates-panel">
      <div className="panel-title">
        <h2>Candidates</h2>
        <button className="icon-button" type="button" disabled={!selectedCount} onClick={onRender} aria-label="Render selected clips">
          <Scissors size={16} /> Render {selectedCount}
        </button>
      </div>
      {clips.length ? (
        <div className="clip-list">
          {clips.map((clip) => (
            <ClipCard key={clip.id} clip={clip} onPatch={onPatch} onAccept={onAccept} onReject={onReject} />
          ))}
        </div>
      ) : (
        <div className="empty-state">No candidates yet</div>
      )}
    </section>
  );
}
