type Props = {
  src?: string | null;
};

export default function PreviewPlayer({ src }: Props) {
  return (
    <section className="panel preview-panel">
      <div className="panel-title">
        <h2>Preview</h2>
      </div>
      {src ? <video src={src} controls /> : <div className="preview-empty">No rendered clip selected</div>}
    </section>
  );
}
