import { Layers2, Trash2 } from 'lucide-react';
import type { Project } from '../types';

type Props = {
  project: Project | null;
  projects: Project[];
  selectedProjectId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onCleanup: (keepId: string) => void;
  busy?: boolean;
};

function seconds(value?: number) {
  if (!value) return '0:00';
  const minutes = Math.floor(value / 60);
  const secs = Math.round(value % 60).toString().padStart(2, '0');
  return `${minutes}:${secs}`;
}

function sourceName(project?: Project | null) {
  if (!project?.source_path) return 'No source';
  return project.source_path.split(/[\\/]/).pop() || project.source_path;
}

function formatDate(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function optionLabel(project: Project) {
  return `${formatDate(project.last_activity_at || project.created_at)} - ${project.name} - ${sourceName(project)} - ${project.id.slice(0, 8)}`;
}

export default function ProjectView({ project, projects, selectedProjectId, onSelect, onDelete, onCleanup, busy = false }: Props) {
  return (
    <section className="panel project-panel">
      <div className="panel-title">
        <h2>Project</h2>
        <select value={selectedProjectId} onChange={(event) => onSelect(event.target.value)} aria-label="Select project">
          <option value="">No project</option>
          {projects.map((item) => (
            <option value={item.id} key={item.id}>
              {optionLabel(item)}
            </option>
          ))}
        </select>
      </div>
      {project ? (
        <>
          <div className="active-project-strip">
            <strong>{sourceName(project)}</strong>
            <span>{project.name} - {project.id.slice(0, 8)} - active {formatDate(project.last_activity_at || project.created_at)}</span>
          </div>
          <div className="project-actions">
            <button
              className="icon-button secondary compact"
              type="button"
              disabled={busy || projects.length < 2}
              onClick={() => onCleanup(project.id)}
              title="Remove every old project and keep this one"
              aria-label="Clean old projects"
            >
              <Layers2 size={15} /> Keep only this
            </button>
            <button
              className="icon-button danger compact"
              type="button"
              disabled={busy}
              onClick={() => onDelete(project.id)}
              title="Delete this project and its output folder"
              aria-label="Delete project"
            >
              <Trash2 size={15} /> Delete
            </button>
          </div>
          <dl className="metadata-grid">
            <div>
              <dt>Status</dt>
              <dd>{project.status}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(project.created_at)}</dd>
            </div>
            <div>
              <dt>Uploaded</dt>
              <dd>{formatDate(project.uploaded_at || undefined)}</dd>
            </div>
            <div>
              <dt>Analyzed</dt>
              <dd>{formatDate(project.analyzed_at || undefined)}</dd>
            </div>
            <div>
              <dt>Rendered</dt>
              <dd>{formatDate(project.rendered_at || undefined)}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{seconds(project.video?.duration)}</dd>
            </div>
            <div>
              <dt>Frame</dt>
              <dd>{project.video ? `${project.video.width}x${project.video.height}` : '-'}</dd>
            </div>
            <div>
              <dt>FPS</dt>
              <dd>{project.video?.fps ? project.video.fps.toFixed(2) : '-'}</dd>
            </div>
            <div>
              <dt>Video</dt>
              <dd>{project.video?.video_codec || '-'}</dd>
            </div>
            <div>
              <dt>Audio</dt>
              <dd>{project.video?.audio_codec || '-'}</dd>
            </div>
            <div>
              <dt>Output</dt>
              <dd>{project.output_dir}</dd>
            </div>
          </dl>
        </>
      ) : (
        <div className="empty-state">No active project</div>
      )}
    </section>
  );
}
