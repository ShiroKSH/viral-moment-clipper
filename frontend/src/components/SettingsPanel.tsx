import { Save } from 'lucide-react';

type Props = {
  settings: Record<string, any> | null;
  onChange: (settings: Record<string, any>) => void;
  onSave: () => void;
};

function updateNested(settings: Record<string, any>, group: string, key: string, value: string | number | boolean) {
  return { ...settings, [group]: { ...settings[group], [key]: value } };
}

export default function SettingsPanel({ settings, onChange, onSave }: Props) {
  if (!settings) return <section className="panel">Settings unavailable</section>;
  return (
    <section className="panel settings-panel">
      <div className="panel-title">
        <h2>Settings</h2>
        <button className="icon-button" type="button" onClick={onSave} aria-label="Save settings">
          <Save size={16} /> Save
        </button>
      </div>
      <div className="settings-grid">
        <label>
          Model
          <input
            value={settings.transcription.model}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'model', event.target.value))}
          />
        </label>
        <label>
          Language
          <input
            value={settings.transcription.language}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'language', event.target.value))}
          />
        </label>
        <label>
          Whisper device
          <select
            value={settings.transcription.device}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'device', event.target.value))}
          >
            <option value="cuda">cuda</option>
            <option value="cpu">cpu</option>
          </select>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.transcription.require_gpu}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'require_gpu', event.target.checked))}
          />
          Hard fail GPU
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.transcription.cpu_fallback}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'cpu_fallback', event.target.checked))}
          />
          Allow CPU fallback
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.transcription.allow_synthetic_fallback}
            onChange={(event) => onChange(updateNested(settings, 'transcription', 'allow_synthetic_fallback', event.target.checked))}
          />
          Old text fallback
        </label>
        <label>
          Render codec
          <select
            value={settings.render.video_codec}
            onChange={(event) => onChange(updateNested(settings, 'render', 'video_codec', event.target.value))}
          >
            <option value="h264_nvenc">h264_nvenc</option>
            <option value="hevc_nvenc">hevc_nvenc</option>
            <option value="libx264">libx264</option>
          </select>
        </label>
        <label>
          FFmpeg hwaccel
          <input
            value={settings.render.hwaccel || ''}
            onChange={(event) => onChange(updateNested(settings, 'render', 'hwaccel', event.target.value || ''))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.render.require_gpu}
            onChange={(event) => onChange(updateNested(settings, 'render', 'require_gpu', event.target.checked))}
          />
          Hard fail NVENC
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.render.gpu_filters}
            onChange={(event) => onChange(updateNested(settings, 'render', 'gpu_filters', event.target.checked))}
          />
          GPU filters
        </label>
        <label>
          Clip count
          <input
            type="number"
            min={1}
            max={40}
            value={settings.clips.target_count}
            onChange={(event) => onChange(updateNested(settings, 'clips', 'target_count', Number(event.target.value)))}
          />
        </label>
        <label>
          Min sec
          <input
            type="number"
            min={5}
            value={settings.clips.min_duration_sec}
            onChange={(event) => onChange(updateNested(settings, 'clips', 'min_duration_sec', Number(event.target.value)))}
          />
        </label>
        <label>
          Max sec
          <input
            type="number"
            min={10}
            value={settings.clips.max_duration_sec}
            onChange={(event) => onChange(updateNested(settings, 'clips', 'max_duration_sec', Number(event.target.value)))}
          />
        </label>
        <label>
          Edit profile
          <select
            value={settings.dynamic_edit.profile}
            onChange={(event) => onChange(updateNested(settings, 'dynamic_edit', 'profile', event.target.value))}
          >
            <option value="banger">banger</option>
            <option value="clean">clean</option>
            <option value="balanced">balanced</option>
            <option value="aggressive">aggressive</option>
            <option value="podcast">podcast</option>
            <option value="gaming">gaming</option>
            <option value="story">story</option>
            <option value="meme">meme</option>
          </select>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.dynamic_edit.scene_detection_enabled ?? true}
            onChange={(event) => onChange(updateNested(settings, 'dynamic_edit', 'scene_detection_enabled', event.target.checked))}
          />
          Source cut detection
        </label>
        <label>
          Scene threshold
          <input
            type="number"
            min={0.03}
            max={0.8}
            step={0.01}
            value={settings.dynamic_edit.scene_threshold ?? 0.1}
            onChange={(event) => onChange(updateNested(settings, 'dynamic_edit', 'scene_threshold', Number(event.target.value)))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.local_llm.enabled}
            onChange={(event) => onChange(updateNested(settings, 'local_llm', 'enabled', event.target.checked))}
          />
          Local LLM
        </label>
        <label>
          Ollama model
          <input
            value={settings.local_llm.model}
            onChange={(event) => onChange(updateNested(settings, 'local_llm', 'model', event.target.value))}
          />
        </label>
        <label>
          Badge
          <input
            value={settings.branding.badge_text}
            onChange={(event) => onChange(updateNested(settings, 'branding', 'badge_text', event.target.value))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.end_card?.enabled ?? true}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'enabled', event.target.checked))}
          />
          End card
        </label>
        <label>
          End headline
          <input
            value={settings.end_card?.headline || ''}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'headline', event.target.value))}
          />
        </label>
        <label>
          End subline
          <input
            value={settings.end_card?.subheadline || ''}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'subheadline', event.target.value))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.end_card?.sound_enabled ?? true}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'sound_enabled', event.target.checked))}
          />
          End sound
        </label>
        <label>
          Sound volume
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={settings.end_card?.sound_volume ?? 0.34}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'sound_volume', Number(event.target.value)))}
          />
        </label>
        <label>
          End channel
          <input
            value={settings.end_card?.channel_text || ''}
            onChange={(event) => onChange(updateNested(settings, 'end_card', 'channel_text', event.target.value))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.subtitles.speaker_colors_enabled}
            onChange={(event) => onChange(updateNested(settings, 'subtitles', 'speaker_colors_enabled', event.target.checked))}
          />
          Speaker colors
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.speakers.enabled}
            onChange={(event) => onChange(updateNested(settings, 'speakers', 'enabled', event.target.checked))}
          />
          Detect speakers
        </label>
        <label>
          Speaker embeddings
          <select
            value={settings.speakers.embedding_backend || 'local'}
            onChange={(event) => onChange(updateNested(settings, 'speakers', 'embedding_backend', event.target.value))}
          >
            <option value="local">local</option>
            <option value="speechbrain">speechbrain</option>
          </select>
        </label>
        <label>
          Max speakers
          <input
            type="number"
            min={1}
            max={8}
            value={settings.speakers.max_speakers}
            onChange={(event) => onChange(updateNested(settings, 'speakers', 'max_speakers', Number(event.target.value)))}
          />
        </label>
        <label>
          Speaker split
          <input
            type="number"
            min={0.05}
            max={0.8}
            step={0.01}
            value={settings.speakers.distance_threshold}
            onChange={(event) => onChange(updateNested(settings, 'speakers', 'distance_threshold', Number(event.target.value)))}
          />
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.subtitles.speaker_labels_enabled}
            onChange={(event) => onChange(updateNested(settings, 'subtitles', 'speaker_labels_enabled', event.target.checked))}
          />
          Speaker labels
        </label>
      </div>
    </section>
  );
}
