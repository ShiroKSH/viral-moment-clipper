# Viral Moment Clipper Agent Instructions

## Project goal
Build a local Windows app that turns long videos into dynamic vertical clips by analyzing speech, finding interesting moments, rendering edited clips, and learning from user feedback.

## Engineering rules
- Keep code modular.
- Do not create one giant script.
- Prefer explicit schemas.
- Validate all external/LLM JSON with Pydantic.
- Always provide fallback paths.
- Do not require cloud APIs for core functionality.
- Do not hardcode user paths.
- Keep Windows compatibility.
- FFmpeg commands must be generated safely as argument lists, not shell strings where possible.
- Long-running work must use job status/progress.
- All important outputs should be saved as JSON sidecar files.

## MVP priority
The MVP must support:
upload -> transcribe -> find moments -> show candidates -> render selected -> export.

## Do not do in MVP
- No auto-upload to YouTube/TikTok.
- No payment system.
- No multi-user cloud backend.
- No complex video editor timeline.
- No promise of guaranteed virality.

## Testing
Add tests for scoring, boundaries, edit plan, rendering command generation, and learning ranker.

## Done means
The app launches with run.bat, opens the local UI, processes a sample mp4, finds clip candidates, renders at least one vertical mp4 with subtitles and badge, and saves metadata.
