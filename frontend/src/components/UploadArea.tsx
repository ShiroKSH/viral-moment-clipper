import { Upload } from 'lucide-react';

type Props = {
  file: File | null;
  onFile: (file: File) => void;
};

export default function UploadArea({ file, onFile }: Props) {
  return (
    <label
      className="upload-area"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const dropped = event.dataTransfer.files.item(0);
        if (dropped) onFile(dropped);
      }}
    >
      <input
        type="file"
        accept=".mp4,.mov,.mkv,.webm,.avi,video/*"
        onChange={(event) => {
          const selected = event.target.files?.item(0);
          if (selected) onFile(selected);
        }}
      />
      <Upload size={24} aria-hidden="true" />
      <span>{file ? file.name : 'Drop video or browse'}</span>
    </label>
  );
}
