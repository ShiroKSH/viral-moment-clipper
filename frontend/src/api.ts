import type { AnalysisState, ClipCandidate, JobRecord, LearningSummary, Project } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:7878/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail));
  }
  return response.json() as Promise<T>;
}

export function getHealth() {
  return request<Record<string, unknown>>('/health');
}

export function getSettings() {
  return request<Record<string, unknown>>('/settings');
}

export function saveSettings(settings: Record<string, unknown>) {
  return request<Record<string, unknown>>('/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
}

export function createProject(name: string, authorHandle: string, outputDir?: string) {
  return request<Project>('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, author_handle: authorHandle, output_dir: outputDir || null }),
  });
}

export function listProjects() {
  return request<Project[]>('/projects');
}

export function deleteProject(projectId: string) {
  return request<{ deleted: Project }>(`/projects/${projectId}`, { method: 'DELETE' });
}

export function cleanupProjects(keepProjectId: string) {
  return request<{ deleted: Project[]; projects: Project[] }>('/projects/cleanup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keep_project_id: keepProjectId, remove_files: true }),
  });
}

export function uploadVideo(projectId: string, file: File) {
  const body = new FormData();
  body.append('file', file);
  return request<{ project: Project; video: unknown }>(`/projects/${projectId}/upload`, { method: 'POST', body });
}

export function analyzeProject(projectId: string) {
  return request<JobRecord>(`/projects/${projectId}/analyze`, { method: 'POST' });
}

export function getAnalysis(projectId: string) {
  return request<AnalysisState>(`/projects/${projectId}/analysis`);
}

export function getJob(jobId: string) {
  return request<JobRecord>(`/jobs/${jobId}`);
}

export function cancelJob(jobId: string) {
  return request<JobRecord>(`/jobs/${jobId}/cancel`, { method: 'POST' });
}

export function getLatestProjectJob(projectId: string, activeOnly = false) {
  const params = new URLSearchParams({ project_id: projectId, latest: 'true' });
  if (activeOnly) params.set('active_only', 'true');
  return request<JobRecord | null>(`/jobs?${params.toString()}`);
}

export function updateClip(projectId: string, clipId: string, patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) {
  return request<ClipCandidate>(`/projects/${projectId}/clips/${clipId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export function acceptClip(projectId: string, clipId: string) {
  return request<ClipCandidate>(`/projects/${projectId}/clips/${clipId}/accept`, { method: 'POST' });
}

export function rejectClip(projectId: string, clipId: string) {
  return request<ClipCandidate>(`/projects/${projectId}/clips/${clipId}/reject`, { method: 'POST' });
}

export function renderProject(projectId: string, clipIds?: string[]) {
  return request<JobRecord>(`/projects/${projectId}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clip_ids: clipIds && clipIds.length ? clipIds : null }),
  });
}

export function openOutputFolder(projectId: string) {
  return request<{ path: string }>(`/projects/${projectId}/open-output-folder`);
}

export function getLearningSummary() {
  return request<LearningSummary>('/learning/summary');
}

export function addMetrics(clipId: string, payload: Record<string, unknown>) {
  return request<{ id: string }>(`/clips/${clipId}/metrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
