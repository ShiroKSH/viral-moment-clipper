import { Play, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  acceptClip,
  analyzeProject,
  createProject,
  getAnalysis,
  getHealth,
  getJob,
  getLearningSummary,
  getSettings,
  listProjects,
  openOutputFolder,
  rejectClip,
  renderProject,
  saveSettings,
  updateClip,
  uploadVideo,
} from './api';
import ClipCandidates from './components/ClipCandidates';
import FeedbackPanel from './components/FeedbackPanel';
import OutputView from './components/OutputView';
import ProgressView from './components/ProgressView';
import ProjectView from './components/ProjectView';
import SettingsPanel from './components/SettingsPanel';
import UploadArea from './components/UploadArea';
import type { AnalysisState, ClipCandidate, JobRecord, LearningSummary, Project } from './types';

export default function App() {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisState | null>(null);
  const [learning, setLearning] = useState<LearningSummary | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState('New clip batch');
  const [authorHandle, setAuthorHandle] = useState('@my_youtube_nick');
  const [error, setError] = useState('');

  const activeProject = analysis?.project || projects.find((project) => project.id === selectedProjectId) || null;
  const clips = analysis?.clips || [];
  const busy = job?.status === 'queued' || job?.status === 'running';

  const refreshProjects = useCallback(async () => {
    const nextProjects = await listProjects();
    setProjects(nextProjects);
    if (!selectedProjectId && nextProjects[0]) setSelectedProjectId(nextProjects[0].id);
  }, [selectedProjectId]);

  const refreshAnalysis = useCallback(async (projectId = selectedProjectId) => {
    if (!projectId) return;
    setAnalysis(await getAnalysis(projectId));
    setLearning(await getLearningSummary());
  }, [selectedProjectId]);

  useEffect(() => {
    Promise.all([getHealth(), getSettings(), listProjects(), getLearningSummary()])
      .then(([healthPayload, settingsPayload, projectPayload, learningPayload]) => {
        setHealth(healthPayload);
        setSettings(settingsPayload);
        setProjects(projectPayload);
        setLearning(learningPayload);
        if (projectPayload[0]) setSelectedProjectId(projectPayload[0].id);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (selectedProjectId) refreshAnalysis(selectedProjectId).catch((err) => setError(err.message));
  }, [selectedProjectId, refreshAnalysis]);

  useEffect(() => {
    if (!job || (job.status !== 'queued' && job.status !== 'running')) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getJob(job.job_id);
        setJob(nextJob);
        if (nextJob.status === 'done' || nextJob.status === 'failed') {
          await refreshAnalysis(nextJob.project_id || selectedProjectId);
          await refreshProjects();
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job, refreshAnalysis, refreshProjects, selectedProjectId]);

  const selectedClipIds = useMemo(() => clips.filter((clip) => clip.selected).map((clip) => clip.id), [clips]);

  async function createUpload() {
    if (!file) {
      setError('Select a video file');
      return;
    }
    setError('');
    const project = await createProject(projectName || file.name, authorHandle);
    setSelectedProjectId(project.id);
    await uploadVideo(project.id, file);
    await refreshProjects();
    await refreshAnalysis(project.id);
  }

  async function startAnalysis() {
    if (!activeProject) return;
    setError('');
    setJob(await analyzeProject(activeProject.id));
  }

  async function renderSelected() {
    if (!activeProject) return;
    setError('');
    setJob(await renderProject(activeProject.id, selectedClipIds));
  }

  async function patchClip(clipId: string, patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) {
    if (!activeProject) return;
    await updateClip(activeProject.id, clipId, patch);
    await refreshAnalysis(activeProject.id);
  }

  async function markAccepted(clipId: string) {
    if (!activeProject) return;
    await acceptClip(activeProject.id, clipId);
    await refreshAnalysis(activeProject.id);
  }

  async function markRejected(clipId: string) {
    if (!activeProject) return;
    await rejectClip(activeProject.id, clipId);
    await refreshAnalysis(activeProject.id);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Viral Moment Clipper</h1>
          <p>Local clip candidates, render plans, feedback ranking.</p>
        </div>
        <div className="health-row">
          <span className={health?.ffprobe ? 'dot ok' : 'dot bad'} />
          <span>ffprobe</span>
          <span className={health?.ffmpeg ? 'dot ok' : 'dot bad'} />
          <span>ffmpeg</span>
        </div>
      </header>

      {error ? <div className="error-box top-error">{error}</div> : null}

      <section className="command-band">
        <div className="field-line">
          <label>
            Project name
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
          </label>
          <label>
            Handle
            <input value={authorHandle} onChange={(event) => setAuthorHandle(event.target.value)} />
          </label>
        </div>
        <UploadArea file={file} onFile={setFile} />
        <div className="command-actions">
          <button className="icon-button" type="button" disabled={busy} onClick={createUpload}>
            <RefreshCw size={16} /> Upload
          </button>
          <button className="icon-button primary" type="button" disabled={!activeProject || busy} onClick={startAnalysis}>
            <Play size={16} /> Analyze
          </button>
        </div>
      </section>

      <div className="workbench">
        <div className="left-rail">
          <ProjectView project={activeProject} projects={projects} selectedProjectId={selectedProjectId} onSelect={setSelectedProjectId} />
          <ProgressView job={job} />
          <SettingsPanel settings={settings} onChange={setSettings} onSave={() => settings && saveSettings(settings).then(setSettings).catch((err) => setError(err.message))} />
        </div>
        <ClipCandidates clips={clips} onPatch={patchClip} onAccept={markAccepted} onReject={markRejected} onRender={renderSelected} />
        <div className="right-rail">
          <OutputView project={activeProject} clips={clips} onOpenFolder={() => activeProject && openOutputFolder(activeProject.id).catch((err) => setError(err.message))} />
          <FeedbackPanel learning={learning} transcriptPreview={analysis?.transcript_preview || ''} />
        </div>
      </div>
    </main>
  );
}
