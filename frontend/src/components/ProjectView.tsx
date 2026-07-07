import type { Project } from '../types';

type Props = {
  project: Project | null;
  projects: Project[];
  selectedProjectId: string;
  onSelect: (id: string) => void;
};

function seconds(value?: number) {
  if (!value) return '0:00';
  const minutes = Math.floor(value / 60);
  const secs = Math.round(value % 60).toString().padStart(2, '0');
  return `${minutes}:${secs}`;
}

export default function ProjectView({ project, projects, selectedProjectId, onSelect }: Props) {
  return (
    <section className="panel project-panel">
      <div className="panel-title">
        <h2>Project</h2>
        <select value={selectedProjectId} onChange={(event) => onSelect(event.target.value)} aria-label="Select project">
          <option value="">No project</option>
          {projects.map((item) => (
            <option value={item.id} key={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      {project ? (
        <dl className="metadata-grid">
          <div>
            <dt>Status</dt>
            <dd>{project.status}</dd>
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
        </dl>
      ) : (
        <div className="empty-state">No active project</div>
      )}
    </section>
  );
}
