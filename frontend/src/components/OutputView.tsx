import { FolderOpen } from 'lucide-react';
import type { ClipCandidate, Project } from '../types';

type Props = {
  project: Project | null;
  clips: ClipCandidate[];
  onOpenFolder: () => void;
};

export default function OutputView({ project, clips, onOpenFolder }: Props) {
  const rendered = clips.filter((clip) => clip.rendered);
  return (
    <section className="panel output-panel">
      <div className="panel-title">
        <h2>Output</h2>
        <button className="icon-button secondary" type="button" disabled={!project} onClick={onOpenFolder} aria-label="Open output folder">
          <FolderOpen size={16} /> Folder
        </button>
      </div>
      <div className="path-line">{project?.output_dir || '-'}</div>
      {rendered.length ? (
        <ul className="output-list">
          {rendered.map((clip) => (
            <li key={clip.id}>
              <strong>{clip.id}</strong>
              <span>{clip.output_path}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-state">No rendered files</div>
      )}
    </section>
  );
}
