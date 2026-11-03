# Contributing to clipforge

Thanks for helping! clipforge stays useful by staying small. Three house rules:

1. **Stdlib only.** No new pip dependencies. ffmpeg/ffprobe are the only external tools.
2. **Tests stay green.** Run `python -m unittest discover -s tests` before opening a PR; add a test for new behavior (end-to-end ffmpeg tests use tiny generated videos, keep them fast).
3. **Nothing phones home.** No telemetry, no update checks, no network calls.

## Good first issues

- New output presets (e.g. 4:5 feed posts) as named shortcuts
- Better error messages when ffmpeg is missing or the input has no audio
- Windows-path edge cases in filter escaping

## Pull request flow

1. Fork, branch from `main`, keep the change focused.
2. Describe *what changed and why* in the PR; include before/after command output for behavior changes.
3. Squash-friendly, clear commit messages.

Bug reports: include your OS, `ffmpeg -version` first line, the exact command, and the last lines of ffmpeg output.
