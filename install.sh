#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
trap 'printf "\nInstallation failed. Resolve the error above and run install.sh again.\n" >&2' ERR

if [ -z "${PREFIX:-}" ] || [ ! -x "${PREFIX}/bin/pkg" ]; then
  echo 'Error: run this installer in Termux on Android.' >&2
  exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_dir"
printf '\n=== Read Dat v1.0.0: dependency installation ===\n'

# Check the distribution before installing anything.
for file in read_dat.py read_dat_i18n.py; do
  if [ ! -f "$file" ]; then
    echo "Error: missing $file. Download the complete Read Dat project." >&2
    exit 1
  fi
done
if [ ! -d locales ]; then
  echo 'Error: missing locales directory. Download the complete Read Dat project.' >&2
  exit 1
fi

missing=()
command -v python >/dev/null 2>&1 || missing+=(python)
command -v mpv >/dev/null 2>&1 || missing+=(mpv)
command -v termux-clipboard-get >/dev/null 2>&1 || missing+=(termux-api)

if [ "${#missing[@]}" -gt 0 ]; then
  echo "Packages to install: ${missing[*]}"
  pkg update
  pkg install -y "${missing[@]}"
else
  echo 'Python, mpv and the Termux:API commands are available.'
fi

if python -c 'import edge_tts' >/dev/null 2>&1; then
  echo 'Python module edge-tts: available.'
else
  echo 'Installing edge-tts...'
  python -m pip install 'edge-tts==7.3.1'
fi

printf '\nFinal checks:\n'
for command in python mpv termux-clipboard-get; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Error: required command is still missing: $command" >&2
    exit 1
  fi
done

# Load resources from the project directory without changing user settings.
python - <<'PY'
import edge_tts

if not callable(getattr(edge_tts, 'list_voices', None)):
    raise SystemExit('Error: edge-tts does not provide list_voices. Install edge-tts 7.3.1.')
if not callable(getattr(edge_tts, 'Communicate', None)):
    raise SystemExit('Error: edge-tts does not provide Communicate. Install edge-tts 7.3.1.')
try:
    from read_dat_i18n import LANGUAGES, ui
    for language in LANGUAGES:
        ui.use(language)
except (OSError, ValueError, UnicodeError) as exc:
    raise SystemExit(f'Error: missing or invalid translation resources: {exc}') from exc
print(f'All {len(LANGUAGES)} UTF-8 translation files are valid.')
print('Python, mpv, Termux:API commands and edge-tts are available.')
PY

cat <<'MESSAGE'

Read Dat v1.0.0 installation complete.

For clipboard reading, also install the Android Termux:API app matching
your Termux installation and grant the necessary permissions.
The termux-api package alone is not sufficient.

Keep read_dat.py, read_dat_i18n.py and locales/ together in the project folder.
Start Read Dat from that folder:
  python read_dat.py

The first launch uses English. Choose [8] Settings to change the language
and voice. Internet access is required for Edge TTS and voice verification.
MESSAGE
