"""UTF-8 translations, persistent language settings and Edge voice validation."""
import asyncio
import json
from pathlib import Path
import string
import tempfile
import unicodedata

LANGUAGES = {
    'en': ('en-US', 'en-US-AriaNeural'),
    'fr': ('fr-FR', 'fr-FR-DeniseNeural'),
    'es': ('es-ES', 'es-ES-ElviraNeural'),
    'it': ('it-IT', 'it-IT-ElsaNeural'),
    'de': ('de-DE', 'de-DE-KatjaNeural'),
    'jp': ('ja-JP', 'ja-JP-NanamiNeural'),
    'kr': ('ko-KR', 'ko-KR-SunHiNeural'),
    'zh': ('zh-CN', 'zh-CN-XiaoxiaoNeural'),
    'vi': ('vi-VN', 'vi-VN-HoaiMyNeural'),
    'km': ('km-KH', 'km-KH-SreymomNeural'),
    'th': ('th-TH', 'th-TH-NiwatNeural'),
    'ru': ('ru-RU', 'ru-RU-SvetlanaNeural'),
}
LOCALES_DIR = Path(__file__).resolve().parent / 'locales'


def fields(value):
    return {field for _, field, _, _ in string.Formatter().parse(value) if field}


class Localization:
    def __init__(self, directory=LOCALES_DIR):
        self.directory = Path(directory)
        self.language = 'en'
        self.messages = self.read('en')
        self.english = self.messages

    def read(self, language):
        with (self.directory / f'{language}.json').open(encoding='utf-8') as stream:
            messages = json.load(stream)
        if not isinstance(messages, dict) or not all(isinstance(v, str) for v in messages.values()):
            raise ValueError('Translation resources must be objects containing strings')
        return messages

    def use(self, language):
        if language not in LANGUAGES:
            raise ValueError('Unknown application language')
        messages = self.read(language)
        if messages.keys() != self.english.keys():
            raise ValueError('Translation keys do not match English resources')
        for key, value in messages.items():
            if fields(value) != fields(self.english[key]):
                raise ValueError(f'Translation placeholders do not match: {key}')
        self.language, self.messages = language, messages

    def text(self, key, **values):
        return self.messages[key].format(**values)


def config_path():
    return Path.home() / '.config' / 'read-dat' / 'config.json'


def save_language(language, path=None):
    """Replace atomically so interrupted writes cannot leave partial JSON."""
    if language not in LANGUAGES:
        raise ValueError('Unknown application language')
    path = Path(path) if path is not None else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.config-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'language': language}, stream, ensure_ascii=False)
            stream.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_language(path=None):
    """Return (language, notice_key); recover safely from malformed settings."""
    path = Path(path) if path is not None else config_path()
    notice = None
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
        language = data.get('language') if isinstance(data, dict) else None
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ValueError('Unknown saved language')
        return language, None
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeError):
        notice = 'config_invalid'
    try:
        save_language('en', path)
    except OSError:
        notice = 'config_write_failed'
    return 'en', notice


class VoiceCatalog:
    """Accept only exact voice/locale pairs returned by Edge's supported API."""
    def __init__(self):
        self.available = None

    async def refresh(self):
        import edge_tts
        self.available = None
        voices = await asyncio.wait_for(edge_tts.list_voices(), timeout=15)
        if not isinstance(voices, list) or not voices:
            raise ValueError('Edge TTS returned an empty or invalid voice list')
        available = {(v.get('Locale'), v.get('ShortName'))
                     for v in voices if isinstance(v, dict)
                     and isinstance(v.get('Locale'), str) and isinstance(v.get('ShortName'), str)}
        if not available:
            raise ValueError('Edge TTS returned no valid voices')
        self.available = available

    def supports(self, language):
        return self.available is not None and LANGUAGES[language] in self.available


def cell_width(character):
    """Approximate terminal columns without adding a Unicode dependency."""
    if unicodedata.category(character) in ('Mn', 'Me', 'Cf'):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ('W', 'F') else 1


def take_columns(text, width):
    used = 0
    end = 0
    for end, character in enumerate(text, 1):
        size = cell_width(character)
        if used + size > width:
            return text[:end - 1], text[end - 1:]
        used += size
    return text, ''


ui = Localization()
tr = ui.text
