import type { ClipCandidate } from '../types';

type Props = {
  clip: ClipCandidate;
  onPatch: (patch: Partial<Pick<ClipCandidate, 'start' | 'end' | 'selected' | 'edit_profile'>>) => void;
};

export default function ClipEditor({ clip, onPatch }: Props) {
  return (
    <div className="clip-editor">
      <label>
        Start
        <input type="number" step="0.1" value={clip.start} onChange={(event) => onPatch({ start: Number(event.target.value) })} />
      </label>
      <label>
        End
        <input type="number" step="0.1" value={clip.end} onChange={(event) => onPatch({ end: Number(event.target.value) })} />
      </label>
      <label>
        Profile
        <select value={clip.edit_profile} onChange={(event) => onPatch({ edit_profile: event.target.value })}>
          <option value="clean">clean</option>
          <option value="balanced">balanced</option>
          <option value="aggressive">aggressive</option>
          <option value="podcast">podcast</option>
          <option value="gaming">gaming</option>
          <option value="banger">banger</option>
          <option value="story">story</option>
          <option value="meme">meme</option>
        </select>
      </label>
    </div>
  );
}
