[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

# MusicScore v1 — Personal score client

A local Windows application for MuScriptor transcription, a score library, transposition, note editing, piano/guitar chord annotations, audition, and MuseScore editing.

Built on [MuScriptor](https://github.com/muscriptor/muscriptor), [MuseScore](https://github.com/musescore/MuseScore), and [AccoMontage2](https://github.com/billyblu2000/AccoMontage2), with a native PySide6 desktop interface. The current source version is **v1 (1.0.0)**, an experimental personal-use release; all features are not necessarily stable.

## v1 status and known issues

Many compatibility issues have occurred across separation, transcription, chord analysis, notation conversion, editing, version history, and playback after audio import. Fixes include postprocessing failures caused by unsupported chord names, scores failing to open because of unpitched percussion, duplicated history text, and crashes from recursive layout with long titles. **Many issues are expected to remain.** These fixes do not resolve every compatibility problem; generated scores still require manual proofreading.

**Harmony arrangement is not yet a complete, usable feature.** The AccoMontage2 interface and generation workflow are integrated, and ordinary harmony generation has worked, but style filtering still produces a “no material of matching length” error. Full accompaniment is disabled because additional model resources are missing. Available styles are standard pop, complex pop, dark, and R&B; successful generation with the selected style is not guaranteed until this issue is fixed. Input checks currently require a monophonic melody, 4/4 meter, constant tempo, and a 4- or 8-bar phrase. Failures preserve the original melody version.

The v1 source passed 56 tests. Local transcription, CUDA separation, score previews, and parts of arrangement have been checked previously; the test count does not guarantee usability in every scenario.

## Branch organization

`main` contains the integrated application; `v1` preserves the uploaded release snapshot. Feature branches start from the same v1 source and retain shared dependencies for later merging. They are not independent, reduced applications. Each feature branch describes its maintenance scope in `docs/BRANCH_SCOPE.md`.

| Branch | Main scope | Main files |
| --- | --- | --- |
| `feature/native-client` | Qt interface, player, recording, and startup | `qt_client.py`, `desktop.py`, startup scripts, `static/icons/` |
| `feature/transcription` | Local/remote MuScriptor transcription and model downloads | `transcribe_worker.py`, `model_download.py`, transcription endpoints in `app.py` |
| `feature/audio-separation` | Audio/video input, optional separation, stem audition | `separation_worker.py`, `separator-requirements.txt`, media endpoints |
| `feature/score-editing` | MuseScore, transposition, note editing, chords, derived notation | `music.py`, `notation.py`, editing endpoints |
| `feature/library-export` | Score library, version history, Recycle Bin, exports | Project/version endpoints in `app.py`, corresponding `qt_client.py` views |
| `feature/ai-assistant` | Assistant using OpenAI, DeepSeek, and compatible APIs | AI endpoints in `app.py`, AI views in `qt_client.py` |
| `feature/harmony-arrangement` | Unfinished AccoMontage2 harmony arrangement | `arrangement.py`, `arrangement_worker.py`, arrangement endpoints and views |

This repository contains application source, tests, icons, and dependency instructions only. **Do not upload personal scores, recordings, stems, exports, model weights, local settings, credentials, logs, or virtual environments.**

## Preparing a source environment

Install Python 3.12, Git, and MuseScore 4 on Windows, then create the environment at the repository root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -r arrangement-requirements.txt
git submodule update --init --depth 1
git -C tools/AccoMontage2 apply ../../patches/accomontage2-chord-pipeline.patch
```

Choose a GPU build of PyTorch separately according to your GPU and CUDA compatibility; default dependency installation does not guarantee CUDA inference. Install MuseScore and download MuScriptor weights separately, accepting their licenses. AccoMontage2 is a submodule pinned to a commit; its data and models are not copied into this repository, though the submodule may itself contain large reference data. The patch fixes missing arguments in its harmony-only branch. Missing resources for full accompaniment and style-filtering problems remain unresolved.

For separation, create a separate `.separator-venv` and install `separator-requirements.txt`. The original local separation environment shares the main environment's CUDA PyTorch and pins compatible versions as described below. No one-click clean-machine setup script is provided for isolated separation dependencies. This source repository is not a packaged installer ready to download and run.

## Startup

Double-click `MusicScore.lnk` on the desktop or in the application directory, or run `Start.ps1`. The client uses native PySide6 Qt Widgets, without WebView2 or an embedded web page. QtPdf previews scores, and QtMultimedia powers the fixed bottom player. Minimizing, maximizing, resizing, collapsing the sidebar, and recording are supported. Launching again activates the existing window. The old web client is documented as a backup at `work/webview-client-legacy.py`; the default entry point no longer uses it.

Closing the window leaves the local background process running so unfinished transcription/download tasks continue; active tasks trigger a confirmation prompt. No startup-at-boot configuration or Windows system service is installed. To stop the background process completely, run `StopService.ps1` after tasks finish. Reopening starts or reuses the local process without reloading models unnecessarily.

The default local port is `8765`; if occupied, a subsequent free port is selected. The service listens only on `127.0.0.1`, not on the LAN. External links, such as Hugging Face license pages, open in the default browser.

The original local installation is `G:\codex\MusicScore`. The Windows credential service name remains `ScoreDesk` to preserve existing API keys. `CreateShortcut.ps1` recreates the launcher shortcut. Moving the installation requires repairing environment startup scripts and updating the shortcut.

## Local paths and exports

“Application installation directory” in settings shows the actual installation location; its folder button opens that directory. “Score export location” appears beside it and defaults to `G:\codex\MusicScore\exports` in the original setup. Select another directory with the folder button or enter a full path and save.

MusicXML, MIDI, MSCZ, PDF, and the current notation's PDF export buttons write directly to the selected export directory and show the actual path. Subdirectories are organized by title, project ID, and version. Repeated exports add a numeric suffix without overwriting files. The library, original inputs, and version data remain in `library/` under the installation; changing the export directory does not move the library.

## First-time settings

1. Sign in to Hugging Face and accept the official [medium](https://huggingface.co/MuScriptor/muscriptor-medium) and [small](https://huggingface.co/MuScriptor/muscriptor-small) model licenses.
2. Enter a Hugging Face read token in settings, save it, and download medium and small. Credentials are stored in Windows Credential Manager.
3. The MuseScore executable path is usually detected automatically; you can also select the full path to `MuseScore4.exe`.

Weights are cached in `models/`; scores and original inputs are in `library/`. Deleted content goes to the Windows Recycle Bin, rather than a local `trash/` folder. Failed downloads are not shown as cached. Local options are small, medium, and large, with medium selected by default, CUDA float16, and batch size 1. GPU tasks run serially. Large requires separate license acceptance on its official model page and a download in settings. Measure VRAM and speed on your own machine; choose a smaller model if memory is insufficient.

Settings and production status show download progress for small, medium, and large. The main status bar reports actual downloaded bytes, total size, percentage, and recent speed. While file information is being fetched, progress is indeterminate; no percentage is invented. Only completed downloads show 100%. Repeated clicks do not create duplicate jobs for the same model. Retries can reuse Hugging Face cache and resume partial downloads.

401/403 means Hugging Face denied access, not that a download continues in the background. Sign in to the account associated with the token, accept the model's license, and use a valid token with access.

## Remote APIs and AI assistant

These APIs serve different purposes:

- **Remote MuScriptor:** configure separate official-compatible MuScriptor endpoints running small, medium, and large weights. The client calls `/transcribe/midi` with multipart fields `file` and optional `instruments`, receiving standard MIDI. The model must already be deployed remotely. A ChatGPT/DeepSeek endpoint cannot replace the music model. Nonlocal addresses require HTTPS.
- **AI assistant:** supports OpenAI, DeepSeek, and OpenAI-compatible services through `/chat/completions`. Configure the service URL, an accessible model ID, and API key. The assistant advises from score notes; it does not run MuScriptor weights, claim to have heard the audio, or automatically rewrite notation. Requests include at most 1000 note events.

The application also exposes `POST /api/transcribe`, with form fields `file`, `mode` (local/remote), `model`, and `instruments`. It returns a job/project ID; query `/api/status` for progress. See `/docs` for API details.

## Usage and versions

For audio/video uploads, FFmpeg extracts the first audio track as mono 24 kHz WAV while preserving the original file. MIDI, MusicXML, and MSCZ imports are also supported. Each edit creates a new version; a failed export does not replace the current version.

QtMultimedia supports microphone recording, pause/resume, and stop. Stopping imports the recording into the library for audition, separation, or direct transcription. Windows settings control microphone permissions, and recording failures are reported. Qt recording does not guarantee disabling automatic gain or system effects on every driver.

## Optional stem separation

After audio/video import, FFmpeg extracts the stereo original mix. Transcribe that mix directly or separate it first. Separation uses nomadkaraoke/python-audio-separator 0.47.0 and offers htdemucs_6s (six stems), htdemucs (four), and UVR_MDXNET_KARA_2 (vocals/accompaniment). Six stems are vocals, drums, bass, guitar, piano, and other instruments. There is no separate violin stem, and acoustic/electric guitar separation is not guaranteed. Audition, seek, and export each stem in the bottom player, then transcribe the selected stem and edit in MuseScore.

The separator runs in `.separator-venv/`; models are cached in `models/separator/`, and stems are in each project's `stems/`. Separation dependencies are isolated from MuScriptor to avoid rotary-embedding-torch conflicts. CUDA torch 2.11.0+cu128 is shared from the main environment; ONNX Runtime GPU is pinned to 1.23.2 for CUDA 12 compatibility. Avoid automatically installing CPU torch over the shared CUDA runtime when updating this environment. Separation and transcription share a serial queue with pause, resume, and cancellation. First use downloads the selected separation model. Originals remain unchanged; deleting a song moves its stems and project records together to the Windows Recycle Bin.

“Score audition” in the bottom player synthesizes notes; it is neither the original recording nor MuseScore's complete instrument engine. Editing, transposition, chord analysis, version switching, AI assistance, downloads, and the default export path continue using the existing local service.

Separation acknowledgments: [nomadkaraoke/python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) and upstream Ultimate Vocal Remover / UVR and Demucs authors. Code and models follow their respective licenses.

The library supports search, PDF viewing, MusicXML/MIDI/MSCZ/PDF export, note edits, transposition, chord reidentification, version switching, and archiving. Built-in playback is basic synthesis; use MuseScore for instrument sounds and full performance control.

A trash button beside each library item allows deletion without opening the score. After confirmation, original inputs, scores, all versions, and project records go to the Windows Recycle Bin. Recycling failures report an error without falling back to permanent deletion. Independent copies exported elsewhere remain. Scores being transcribed or edited cannot be deleted.

The MuseScore button opens an `edited.mscz` copy of the current version. After saving in MuseScore, use the adjacent sync button to create a new library version. Automatic edits exchange MusicXML; complex articulations and fine layout may change during conversion, while the original MSCZ editing copy is retained. Transposition/note edits discard old string/fret annotations; review and adjust TAB in MuseScore.

Automatic chords use simultaneously sounding notes in piano/guitar parts, identified by music21 and written as Harmony annotations. These are candidates: arpeggios, incomplete chords, ornaments, complex jazz harmony, and transcription errors may cause omissions or wrong labels. Parts such as violin do not receive automatic guitar chord annotations.

## Guitar and piano notation

- **Guitar:** melody in numbered notation, chord names, and TAB share a page; PDF and MSCZ are available. Melody currently uses the highest pitch of each note event, not a melody-separation model. Complex fingerstyle/polyphony requires proofreading. TAB uses MuseScore's default six-string tuning; automatic string/fret choices may not be optimal.
- **Piano:** two-hand staff notation and two-hand numbered notation are selectable. Existing left/right Staff data is preserved; initial monophonic imports split at middle C and are marked automatically assigned. Adjust crossed hands/voices in the master score.
- Conversions share the master MusicXML without retranscribing audio. Transposition, note edits, and master synchronization regenerate derived notation. Original pitch, duration, and hand assignments remain. Extracting notes from images/PDF is unsupported.
- Numbered notation is an experimental conversion layer, not complete native MuseScore support. Visible number text represents pitch while underlying notes remain. Digits, accidentals, octave dots, rests, and common durations are supported. Polyphony, ties, special rhythms, and complex layout are not fully verified; publication-quality numbered notation is not guaranteed. Minor keys use the relative major's tonic as 1.
- “Open notation” opens derived MSCZ; “MuseScore” opens the synchronizable master editing copy. Edit and sync the master, then regenerate notation; directly editing derived number text does not change pitch. The derived guitar melody is muted in MuseScore to avoid doubling TAB playback.

Native numbered notation remains under [MuseScore discussion](https://github.com/orgs/musescore/discussions/22698). Standard staff notation and TAB remain available and are not overwritten by the numbered view.

## Validation

Run `.venv/Scripts/python.exe -m pytest -q`. Actual transcription requires authorized official model weights. External AI services are not called without a valid API key.

Dependencies: [MuScriptor](https://github.com/muscriptor/muscriptor), [MuseScore](https://github.com/musescore/MuseScore), [AccoMontage2](https://github.com/billyblu2000/AccoMontage2), [music21](https://github.com/cuthbertLab/music21), [Lucide](https://github.com/lucide-icons/lucide), and [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator). MuScriptor weights follow CC BY-NC 4.0. Dependency code, reference data, and models follow their upstream licenses; this repository does not change those licenses.
