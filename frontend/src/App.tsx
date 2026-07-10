import { FilePlus2, Play, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  acceptClip,
  analyzeProject,
  cleanupProjects,
  createProject,
  deleteProject,
  getAnalysis,
  getHealth,
  getJob,
  getLatestProjectJob,
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
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');

  const activeProject = (analysis && analysis.project.id === selectedProjectId ? analysis.project : projects.find((project) => project.id === selectedProjectId)) || null;
  const clips = analysis && analysis.project.id === selectedProjectId ? analysis.clips : [];
  const jobBusy = job?.status === 'queued' || job?.status === 'running';
  const busy = jobBusy || uploading;
  const canAnalyze = Boolean(activeProject?.source_path) && !busy;

  function defaultProjectName(nextFile: File) {
    return nextFile.name.replace(/\.[^.]+$/, '').trim().slice(0, 100) || 'New clip batch';
  }

  function chooseFile(nextFile: File) {
    setFile(nextFile);
    setUploadMessage('');
    setProjectName((current) => (current.trim() && current !== 'New clip batch' ? current : defaultProjectName(nextFile)));
  }

  const refreshProjects = useCallback(async (preferredProjectId?: string) => {
    const nextProjects = await listProjects();
    setProjects(nextProjects);
    const preferredExists = preferredProjectId && nextProjects.some((project) => project.id === preferredProjectId);
    const selectedExists = selectedProjectId && nextProjects.some((project) => project.id === selectedProjectId);
    const nextSelectedProjectId = preferredExists ? preferredProjectId : selectedExists ? selectedProjectId : nextProjects[0]?.id || '';
    setSelectedProjectId(nextSelectedProjectId);
    return nextProjects;
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
    setAnalysis(null);
    if (selectedProjectId) refreshAnalysis(selectedProjectId).catch((err) => setError(err.message));
  }, [selectedProjectId, refreshAnalysis]);

  useEffect(() => {
    if (!job || (job.status !== 'queued' && job.status !== 'running')) return;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getJob(job.job_id);
        setJob(nextJob);
        if (nextJob.status === 'done' || nextJob.status === 'failed') {
          const jobProjectId = nextJob.project_id || selectedProjectId;
          if (jobProjectId) setSelectedProjectId(jobProjectId);
          await refreshProjects(jobProjectId || undefined);
          if (jobProjectId) await refreshAnalysis(jobProjectId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job, refreshAnalysis, refreshProjects, selectedProjectId]);

  const selectedClipIds = useMemo(() => clips.filter((clip) => clip.selected).map((clip) => clip.id), [clips]);

  useEffect(() => {
    if (!selectedProjectId || jobBusy) return;
    let cancelled = false;
    getLatestProjectJob(selectedProjectId, true)
      .then((latestJob) => {
        if (!cancelled && latestJob && (latestJob.status === 'queued' || latestJob.status === 'running')) {
          setJob(latestJob);
        }
      })
      .catch(() => {
        // Missing in-memory jobs after a backend restart should not block normal use.
      });
    return () => {
      cancelled = true;
    };
  }, [jobBusy, selectedProjectId]);

  async function createUpload() {
    if (!file) {
      setError('Select a video file');
      return;
    }
    try {
      setError('');
      setUploading(true);
      setUploadMessage('Creating project...');
      setJob(null);
      setAnalysis(null);
      const project = await createProject(projectName || file.name, authorHandle);
      setSelectedProjectId(project.id);
      setUploadMessage(`Uploading to ${project.id.slice(0, 8)}...`);
      const uploaded = await uploadVideo(project.id, file);
      setUploadMessage(`Ready: ${uploaded.project.name} (${uploaded.project.id.slice(0, 8)})`);
      setFile(null);
      setProjectName('New clip batch');
      await refreshProjects(project.id);
      await refreshAnalysis(project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  }

  async function removeProject(projectId: string) {
    if (!window.confirm('Delete this project and its output folder?')) return;
    try {
      setError('');
      await deleteProject(projectId);
      setAnalysis(null);
      await refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function keepOnlyProject(projectId: string) {
    if (!window.confirm('Delete every old project and keep only the selected one?')) return;
    try {
      setError('');
      const payload = await cleanupProjects(projectId);
      setProjects(payload.projects);
      setSelectedProjectId(projectId);
      await refreshAnalysis(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function startAnalysis() {
    if (!activeProject?.source_path) {
      setError('Select or upload a source video first');
      return;
    }
    try {
      setError('');
      setAnalysis(null);
      const nextJob = await analyzeProject(activeProject.id);
      setJob(nextJob);
      await refreshProjects(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function renderSelected() {
    if (!activeProject) return;
    try {
      setError('');
      const nextJob = await renderProject(activeProject.id, selectedClipIds);
      setJob(nextJob);
      await refreshProjects(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function patchClip(clipId: string, patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) {
    if (!activeProject) return;
    await updateClip(activeProject.id, clipId, patch);
    await refreshAnalysis(activeProject.id);
  }

  async function markAccepted(clipId: string) {
    if (!activeProject) return;
    try {
      setError('');
      await acceptClip(activeProject.id, clipId);
      await refreshAnalysis(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function markRejected(clipId: string) {
    if (!activeProject) return;
    try {
      setError('');
      await rejectClip(activeProject.id, clipId);
      await refreshAnalysis(activeProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Viral Moment Clipper</h1>
          <p>Local clip candidates, render plans, feedback ranking.</p>
        </div>
        <div className="status-stack">
          <div className="health-row">
            <span className={health?.ffprobe ? 'dot ok' : 'dot bad'} />
            <span>ffprobe</span>
            <span className={health?.ffmpeg ? 'dot ok' : 'dot bad'} />
            <span>ffmpeg</span>
          </div>
          <div className="runtime-row">
            <span>
              Whisper target {settings?.transcription?.device || '-'} / {settings?.transcription?.compute_type || '-'}
              {settings?.transcription?.cpu_fallback ? ' · CPU fallback allowed' : ' · strict'}
            </span>
            <span>
              Render target {settings?.render?.video_codec || '-'} / {settings?.render?.hwaccel || 'no hwaccel'}
              {settings?.render?.gpu_filters ? ' · GPU filters' : ''}
              {settings?.render?.require_gpu ? ' · strict' : ` · ${settings?.render?.fallback_video_codec || 'CPU'} fallback allowed`}
            </span>
            <span>
              Speakers {settings?.speakers?.enabled ? `${settings.speakers.embedding_backend || 'local'} / ${settings.speakers.max_speakers}` : 'off'}
            </span>
          </div>
        </div>
      </header>

      {error ? <div className="error-box top-error">{error}</div> : null}

      <section className="command-band">
        <div className="upload-form">
          <div className="upload-form-title">
            <FilePlus2 size={17} />
            <strong>New upload</strong>
            {uploadMessage ? <span>{uploadMessage}</span> : null}
          </div>
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
        </div>
        <UploadArea file={file} onFile={chooseFile} />
        <div className="command-actions">
          <button className="icon-button" type="button" disabled={busy || !file} onClick={createUpload}>
            <RefreshCw className={uploading ? 'spin' : undefined} size={16} /> Create + Upload
          </button>
          <button className="icon-button primary" type="button" disabled={!canAnalyze} onClick={startAnalysis}>
            <Play size={16} /> Analyze
          </button>
        </div>
      </section>

      <div className="workbench">
        <div className="left-rail">
          <ProjectView
            project={activeProject}
            projects={projects}
            selectedProjectId={selectedProjectId}
            onSelect={setSelectedProjectId}
            onDelete={removeProject}
            onCleanup={keepOnlyProject}
            busy={busy}
          />
          <ProgressView job={job} />
          <SettingsPanel settings={settings} onChange={setSettings} onSave={() => settings && saveSettings(settings).then(setSettings).catch((err) => setError(err.message))} />
        </div>
        <ClipCandidates clips={clips} onPatch={patchClip} onAccept={markAccepted} onReject={markRejected} onRender={renderSelected} busy={busy} />
        <div className="right-rail">
          <OutputView project={activeProject} clips={clips} onOpenFolder={() => activeProject && openOutputFolder(activeProject.id).catch((err) => setError(err.message))} />
          <FeedbackPanel learning={learning} transcriptPreview={analysis?.transcript_preview || ''} speakerSummary={analysis?.speaker_summary} />
        </div>
      </div>
    </main>
  );
}
