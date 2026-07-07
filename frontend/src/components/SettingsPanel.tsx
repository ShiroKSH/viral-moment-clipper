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
            <option value="clean">clean</option>
            <option value="balanced">balanced</option>
            <option value="aggressive">aggressive</option>
            <option value="podcast">podcast</option>
            <option value="gaming">gaming</option>
          </select>
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
      </div>
    </section>
  );
}
