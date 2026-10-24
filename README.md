# Read Dat v1.0.0

Read Dat is a lightweight multilingual text-to-speech karaoke application for
Android Termux. It converts pasted text or Android clipboard content into
natural speech while highlighting the currently spoken word in green.

## Features

- Natural Microsoft Edge TTS speech in 12 languages.
- Word highlighting with automatic text scrolling.
- Automatic playback from the beginning, with pause, resume and five-second seeking.
- Text input by pasting or reading the Android clipboard.
- Translated menus, playback controls, instructions and application messages.
- Immediate language and voice changes through Settings.
- Persistent language settings with safe recovery from invalid configuration.
- Temporary MP3 generation and cleanup.
- Automated installation of missing Termux dependencies.

## Requirements

- Android with Termux.
- Python 3.13.
- The Python package `edge-tts` (tested with 7.3.1).
- `mpv` for audio playback.
- The Termux `termux-api` command-line package.
- The separate **Termux:API Android application** for clipboard access.
- An Internet connection for voice verification and speech generation.

Install Termux and Termux:API from compatible sources. The command-line package
does not install the Android application.

## Installation

Open Termux and run:

```bash
pkg update
pkg install -y git
git clone https://github.com/m12-tek/Read-Dat.git
cd Read-Dat
bash install.sh
python read_dat.py
```

The installer checks the application modules and all translation files, installs
missing dependencies, and verifies the installation. Existing dependencies are
kept. It does not modify application code or user settings.

For manual installation:

```bash
pkg update
pkg install -y python mpv termux-api
python -m pip install 'edge-tts==7.3.1'
python read_dat.py
```

Keep `read_dat.py`, `read_dat_i18n.py` and the entire `locales/` directory
together. Start the application with `python read_dat.py`.

## Usage

A fresh installation starts in English:

```text
[1] Paste Text
[2] Read Clipboard

[8] Settings
[0] Exit
```

**Paste Text:** paste one or more lines. Input finishes after two seconds without
a new line. Press Enter if the last line has no line break.

**Read Clipboard:** copy text in Android, then select this option to read it.

Playback starts automatically when the audio, terminal and first frame are ready.
No key press is required to begin.

At the end, playback pauses and the text stays on screen. Press LEFT ARROW to
move back five seconds, then SPACE to listen again. Press ESC to return to the
main menu. The temporary audio remains available until you leave the player.

The terminal screen and scrollback are cleared at startup, when selecting menu
options, when returning to the main menu, and when exiting with **[0] Exit**.

The playback banner shows the application name and status on the first line,
stop/pause controls on the second, and seek controls followed by times on the third. On narrower terminals,
long translated lines wrap instead of hiding information.

## Controls

| Key | Action |
|---|---|
| SPACE | Pause / resume |
| LEFT ARROW | Seek backward five seconds |
| RIGHT ARROW | Seek forward five seconds |
| ESC | Stop playback and return to the menu |

## Supported languages

| Language | Code | Edge TTS voice |
|---|---|---|
| English | en | en-US-AriaNeural |
| French | fr | fr-FR-DeniseNeural |
| Spanish | es | es-ES-ElviraNeural |
| Italian | it | it-IT-ElsaNeural |
| German | de | de-DE-KatjaNeural |
| Japanese | ja | ja-JP-NanamiNeural |
| Korean | ko | ko-KR-SunHiNeural |
| Simplified Chinese | zh | zh-CN-XiaoxiaoNeural |
| Vietnamese | vi | vi-VN-HoaiMyNeural |
| Khmer | km | km-KH-SreymomNeural |
| Thai | th | th-TH-NiwatNeural |
| Russian | ru | ru-RU-SvetlanaNeural |

The menu follows this table's order. Japanese and Korean use the standard
language codes `ja` and `ko`; the application retains its existing `jp` and
`kr` resource filenames and saved-setting values for compatibility.

Configured voices are checked against the live Edge TTS catalog. If a voice
cannot be verified or is unavailable, the application shows an error instead of
silently choosing another language or voice. Availability requires Internet
access and may change.

## Settings

Choose **[8] Settings**, then select a language by number. All interface messages
and the corresponding TTS voice change immediately. Choose **0** to return to the
main menu. The current language is marked with an asterisk.

The interface language and speech language are linked. The application does not
automatically detect the language of the input text.

The selection is saved in `~/.config/read-dat/config.json`, for example:

```json
{"language": "fr"}
```

The directory and configuration file are created automatically. Changes persist
across restarts. Invalid settings recover safely to English. If a setting cannot
be saved, the previous language is retained.

## Project structure

```text
Read-Dat/
├── read_dat.py
├── read_dat_i18n.py
├── install.sh
├── README.md
├── LICENSE
├── CHANGELOG.md
├── .gitignore
└── locales/
    ├── en.json
    ├── fr.json
    ├── es.json
    ├── it.json
    ├── de.json
    ├── jp.json
    ├── kr.json
    ├── zh.json
    ├── vi.json
    ├── km.json
    ├── th.json
    └── ru.json
```

- **read_dat.py:** menus, text input, clipboard access, speech generation,
  playback, IPC, karaoke synchronization and keyboard controls.
- **read_dat_i18n.py:** translation loading, language and voice mappings,
  configuration persistence and voice availability checks.
- **locales/:** the 12 UTF-8 translation resources. Keys and formatting
  placeholders are validated before switching languages.
- **install.sh:** checks project files and installs missing Termux dependencies.

## Karaoke timing and display

Read Dat uses word timing boundaries when available. If Edge TTS supplies only
sentence boundaries, word timings are estimated within each sentence.
Highlighting is therefore approximate. Scripts without spaces are limited by
the existing tokenizer's word segmentation.

Text and interface messages wrap between words to fit the terminal width.
Karaoke text is laid out again as the terminal size changes. Paragraph breaks
and highlighting are preserved. A word longer than an entire line must still
be split.

The terminal font must contain glyphs for the selected language. Wrapping
accounts for wide characters and combining marks; widths for complex scripts
and emoji remain approximate. Text shaping is handled by the terminal.

## Troubleshooting

| Issue | What to check |
|---|---|
| Missing Python or mpv | Run `bash install.sh`, or `pkg install python mpv`. |
| Missing edge-tts | Run `python -m pip install 'edge-tts==7.3.1'`. |
| Clipboard does not work | Install both `pkg install termux-api` and the compatible Termux:API Android app; check Android permissions. |
| Voice verification or generation fails | Check Internet access, then retry. Reopen Settings to refresh the voice catalog. |
| No audible playback | Check Android media volume and audio output. Run `mpv --version` to confirm the player is installed. |
| Missing or damaged translations | Restore the complete `locales/` directory and `read_dat_i18n.py`. |
| Missing non-Latin characters | Select a Termux font with glyphs for the chosen script. |
| Settings cannot be saved | Check permissions on `~/.config/read-dat/`. |

Startup diagnostics are stored in `read_dat_startup.jsonl` in Python's temporary
directory, normally `$TMPDIR` in Termux. Each playback replaces the previous log.
It records startup events and actual mpv positions, without the input text:

```bash
cat "$TMPDIR/read_dat_startup.jsonl"
```

## Data handling

Text is sent to Microsoft Edge TTS for speech generation. Audio is played locally
with mpv. Temporary MP3 files are removed when you leave the player or playback
fails. Voice catalog checks do not send the input text.

## Releases

Read Dat uses semantic versioning. The planned **1.1.0** feature is independent
selection of the interface language and TTS language.

See [CHANGELOG.md](CHANGELOG.md) for release information.

## Project Origins

Read Dat began as a small Bash script for Termux, using Android’s built-in
text-to-speech engine to read text aloud.

It evolved into a Python application with natural Edge TTS voices, interactive
playback controls, karaoke-style highlighting, and multilingual support.

Read Dat v1.0.0 marks the project’s first official public release.

## License

Read Dat is distributed under the [MIT License](LICENSE).

Copyright (c) 2026 m12-tek.
