#!/usr/bin/env python3
"""Read Dat v1.0.0: multilingual TTS karaoke for Android Termux."""
import asyncio
import bisect
import difflib
from collections import deque
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import termios
import time
import tty
import unicodedata
from pathlib import Path

import edge_tts
from read_dat_i18n import (LANGUAGES, VoiceCatalog, cell_width, load_language,
                           save_language, take_columns, tr, ui)

VERSION = '1.0.0'
voices = VoiceCatalog()
GREEN = "\033[1;32m"
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"
WORD_RE = re.compile(r"\w+(?:[’'\-]\w+)*|[^\w\s]+|\s+", re.UNICODE)


def clear_terminal():
    """Clear the screen and scrollback at menu transitions only."""
    sys.stdout.write('\033[2J\033[3J\033[H')
    sys.stdout.flush()


def normalize(word):
    return ''.join(c for c in unicodedata.normalize('NFKD', word).casefold()
                   if c.isalnum())


def clipboard():
    p = subprocess.run(['termux-clipboard-get'], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(tr('clipboard_error'))
    return p.stdout


def paste():
    print_wrapped(tr('paste_instructions'), flush=True)
    first = sys.stdin.readline()
    if not first:
        return ''
    chunks = [first]
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 2.0)
        if not ready:
            break
        line = sys.stdin.readline()
        if not line:
            break
        chunks.append(line)
    return ''.join(chunks)


async def synthesize(text, audio_path):
    timings = []
    communicate = edge_tts.Communicate(text, LANGUAGES[ui.language][1])
    with open(audio_path, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] in ('WordBoundary', 'SentenceBoundary'):
                timings.append((chunk['type'], chunk['offset'] / 10_000_000,
                                chunk.get('duration', 0) / 10_000_000, chunk['text']))
    if not os.path.getsize(audio_path):
        raise RuntimeError(tr('no_audio'))
    return timings


def expand_sentence_boundaries(text, events):
    """Estimate word start times within each spoken sentence.

    Edge TTS 7.3.1 can return SentenceBoundary only. Preserve real sentence
    start/duration and interpolate words within each sentence.
    """
    word_spans = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\w+(?:[’'\-]\w+)*", text)]
    output = []
    cursor = 0
    for kind, start, duration, spoken in events:
        if kind == 'WordBoundary':
            output.append((start, spoken))
            continue
        if kind != 'SentenceBoundary':
            continue
        # Locate sentence in source, falling back to sequential word grouping.
        at = text.find(spoken, cursor)
        if at < 0:
            simplified = spoken.strip()
            at = text.find(simplified, cursor)
            if at >= 0:
                spoken = simplified
        if at >= 0:
            end = at + len(spoken)
            words = [(a,b,w) for a,b,w in word_spans if a >= at and b <= end]
            cursor = end
        else:
            count = len(re.findall(r"\w+(?:[’'\-]\w+)*", spoken))
            words = [(a,b,w) for a,b,w in word_spans if a >= cursor][:count]
            if words:
                cursor = words[-1][1]
        if not words:
            continue
        weights = [max(1.0, len(normalize(w)) ** 0.75) for _,_,w in words]
        total = sum(weights)
        elapsed = 0.0
        for (_, _, w), weight in zip(words, weights):
            output.append((start + duration * elapsed / total, w))
            elapsed += weight
    return sorted(output, key=lambda item: item[0])


def match_words(text, timings):
    """Align Edge word boundaries with original tokens, allowing punctuation changes."""
    tokens = [(m.group(), m.start(), m.end()) for m in WORD_RE.finditer(text)]
    word_ids = [i for i, (token, _, _) in enumerate(tokens) if normalize(token)]
    original = [normalize(tokens[i][0]) for i in word_ids]
    spoken = [(float(t), normalize(w)) for t, w in timings if normalize(w)]
    # WordBoundary usually follows word segmentation; use sequence alignment first.
    matcher = difflib.SequenceMatcher(a=original, b=[w for _, w in spoken], autojunk=False)
    aligned = {}
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == 'equal':
            for x, y in zip(range(a1, a2), range(b1, b2)):
                aligned[y] = word_ids[x]
    # Fall back to normalized character-stream matching for split/merged words.
    chars = []
    for i in word_ids:
        for c in normalize(tokens[i][0]):
            chars.append((c, i))
    stream = ''.join(c for c, _ in chars)
    cursor = 0
    matches = []
    for j, (start, word) in enumerate(spoken):
        at = stream.find(word, cursor, min(len(stream), cursor + max(250, len(word) + 1)))
        if at >= 0:
            idx = chars[at][1]
            cursor = at + len(word)
        else:
            idx = aligned.get(j)
        if idx is not None:
            matches.append((start, idx))
    return tokens, matches


def make_lines(tokens, width):
    """Wrap at whitespace, retaining token IDs for karaoke highlighting."""
    width = max(1, width)
    groups = []
    for index, (part, _, _) in enumerate(tokens):
        for match in re.finditer(r'\n|[^\S\n]+|\S+', part):
            piece = match.group().replace('\t', '    ')
            kind = 'newline' if piece == '\n' else 'space' if piece.isspace() else 'word'
            if groups and kind != 'newline' and groups[-1][0] == kind:
                groups[-1][1].append((index, piece))
            else:
                groups.append((kind, [(index, piece)]))
    lines = [[]]
    length = 0
    pending = []
    for kind, parts in groups:
        if kind == 'newline':
            lines.append([])
            length = 0
            pending = []
            continue
        if kind == 'space':
            pending.extend(parts)
            continue
        word_width = sum(cell_width(c) for _, part in parts for c in part)
        space_width = sum(cell_width(c) for _, part in pending for c in part)
        if length and length + space_width + word_width > width:
            lines.append([])
            length = 0
            pending = []
        elif length + space_width + min(word_width, width) <= width:
            lines[-1].extend(pending)
            length += space_width
        pending = []
        for index, piece in parts:
            while piece:
                segment, rest = take_columns(piece, max(0, width - length))
                if not segment:
                    if not lines[-1]:
                        # A glyph wider than the entire terminal cannot fit.
                        segment, rest = piece[:1], piece[1:]
                    else:
                        lines.append([])
                        length = 0
                        continue
                piece = rest
                lines[-1].append((index, segment))
                length += sum(cell_width(c) for c in segment)
                if piece:
                    lines.append([])
                    length = 0
    # Preserve prompt spacing when it fits; discard trailing wrap whitespace.
    if length + sum(cell_width(c) for _, part in pending for c in part) <= width:
        lines[-1].extend(pending)
    return lines


def wrap_message(message, width=None):
    """Use the same column-aware word wrapping for interface messages."""
    if width is None:
        width = max(2, shutil.get_terminal_size((80, 24)).columns - 2)
    prefix = CLEAR if message.startswith(CLEAR) else ''
    content = message[len(prefix):]
    lines = make_lines([(content, 0, len(content))], width)
    return prefix + '\n'.join(''.join(part for _, part in line) for line in lines)


def print_wrapped(message='', flush=False):
    sys.stdout.write(wrap_message(message) + '\n')
    if flush:
        sys.stdout.flush()


def render(text, tokens, matches, position, paused, duration):
    columns, rows = shutil.get_terminal_size((80, 24))
    width = max(2, columns - 2)
    lines = make_lines(tokens, width)
    starts = [x[0] for x in matches]
    k = bisect.bisect_right(starts, position) - 1
    active = matches[k][1] if k >= 0 else -1
    active_line = next((j for j, line in enumerate(lines)
                        if any(i == active for i, _ in line)), 0)
    state = tr('paused' if paused else 'playing')
    timing = tr('playback_header', position=position, duration=duration)
    header_lines = []
    for header in (f'READ DAT v{VERSION} | {state}', tr('controls'),
                   tr('seek_controls') + ' | ' + timing):
        header_lines.extend(wrap_message(header, width).split('\n'))
    page_height = max(1, rows - len(header_lines) - 3)
    top = max(0, min(active_line - page_height // 2,
                     max(0, len(lines) - page_height)))
    out = [CLEAR, '\n'.join(header_lines), '\n',
           '─' * min(width, columns), '\n']
    for line in lines[top:top + page_height]:
        for i, segment in line:
            out.append((GREEN + segment + RESET) if i == active else segment)
        out.append('\n')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


class MPVIPC:
    def __init__(self, sock):
        self.sock = sock
        self.reader = sock.makefile('rb')
        self.counter = 0
        self.events = deque(maxlen=100)
        self.trace = None

    def record(self, kind, data):
        if self.trace is not None:
            self.trace.write(json.dumps({'at': time.monotonic(), kind: data},
                                        ensure_ascii=False) + '\n')
            self.trace.flush()

    def read_reply(self):
        line = self.reader.readline()
        if not line:
            raise RuntimeError(tr('mpv_closed'))
        reply = json.loads(line)
        self.record('received', reply)
        if 'event' in reply:
            self.events.append(reply)
        return reply

    def wait_event(self, name, timeout=10.0):
        """Keep events received before a command's reply; do not lose load/seek completion."""
        deadline = time.monotonic() + timeout
        previous_timeout = self.sock.gettimeout()
        try:
            while True:
                while self.events:
                    event = self.events.popleft()
                    if event['event'] == name:
                        return event
                    if event['event'] in ('end-file', 'shutdown'):
                        raise RuntimeError(tr('mpv_event_error', name=name, details=repr(event)))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(tr('mpv_event_timeout', name=name))
                self.sock.settimeout(remaining)
                self.read_reply()
        except socket.timeout as exc:
            raise RuntimeError(tr('mpv_event_timeout', name=name)) from exc
        finally:
            self.sock.settimeout(previous_timeout)

    def command(self, args):
        self.counter += 1
        req = self.counter
        request = {'command': args, 'request_id': req}
        self.record('sent', request)
        self.sock.sendall((json.dumps(request) + '\n').encode())
        while True:
            reply = self.read_reply()
            if reply.get('request_id') == req:
                return reply

    def close(self):
        self.reader.close()
        self.sock.close()


def startup_command(conn, args):
    """Require an acknowledged IPC command during startup only."""
    reply = conn.command(args)
    if reply.get('error') != 'success':
        raise RuntimeError(tr('mpv_command_error', details=f'{args!r}: {reply!r}'))
    return reply.get('data')


def wait_for_audio(conn, near_zero=False, timeout=10.0):
    """Confirm loaded audio, pause and completed seeking from real IPC data."""
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        for name in ('idle-active', 'pause', 'seeking', 'time-pos', 'duration'):
            reply = conn.command(['get_property', name])
            error = reply.get('error')
            if error == 'success':
                state[name] = reply.get('data')
            elif error == 'property unavailable':
                # Normal while loadfile/seek is still being processed.
                state[name] = None
            else:
                raise RuntimeError(tr('mpv_property_error', name=name, details=repr(reply)))
        if state['pause'] is False:
            raise RuntimeError(tr('mpv_pause_lost', details=repr(state)))
        position, duration = state['time-pos'], state['duration']
        if (state['idle-active'] is False and state['pause'] is True
                and state['seeking'] is False
                and type(position) in (int, float)
                and type(duration) in (int, float) and duration > 0
                and (not near_zero or 0 <= position < .05)):
            return float(position), float(duration)
        time.sleep(.05)
    target = tr('target_zero' if near_zero else 'target_load')
    raise RuntimeError(tr('mpv_timeout', target=target, details=repr(state)))


def parse_key(buffer):
    # Return (key, remainder), preserving incomplete escape sequences.
    if not buffer:
        return None, buffer
    if buffer[0] != 27:
        return ('space' if buffer[0] == 32 else 'other'), buffer[1:]
    if len(buffer) == 1:
        return None, buffer
    if buffer[1] not in (ord('['), ord('O')):
        return 'esc', buffer[1:]
    if len(buffer) < 3:
        return None, buffer
    # CSI sequences: ESC [ D, ESC [ 1 ; 5 D, etc.
    for j in range(2, min(len(buffer), 24)):
        c = buffer[j]
        if 0x40 <= c <= 0x7e:
            key = 'right' if c == ord('C') else 'left' if c == ord('D') else 'other'
            return key, buffer[j+1:]
    return None, buffer


def player(text, audio, timings, socket_path):
    expanded = expand_sentence_boundaries(text, timings)
    tokens, matches = match_words(text, expanded)
    sentences = sum(t[0] == 'SentenceBoundary' for t in timings)
    words = sum(t[0] == 'WordBoundary' for t in timings)
    print_wrapped(tr('edge_markers', words=words, sentences=sentences, aligned=len(matches)), flush=True)
    if not matches:
        print_wrapped(tr('no_alignment'))
        time.sleep(2)
    # Embedded playback must not inherit resume offsets, profiles or user scripts.
    command = ['mpv', '--no-config', '--load-scripts=no', '--resume-playback=no',
               '--start=0', '--no-video', '--no-terminal', '--really-quiet',
               '--keep-open=yes', '--keep-open-pause=yes',
               '--idle=yes', '--pause', '--input-ipc-server=' + socket_path]
    log_path = Path(tempfile.gettempdir()) / 'read_dat_startup.jsonl'
    trace = None
    try:
        trace = log_path.open('w', encoding='utf-8')
    except OSError:
        pass
    proc = None
    sock = None
    conn = None
    old = None
    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if os.path.exists(socket_path):
                try:
                    sock = socket.socket(socket.AF_UNIX)
                    sock.settimeout(2)
                    sock.connect(socket_path)
                    conn = MPVIPC(sock)
                    conn.trace = trace
                    conn.record('startup', {'version': VERSION, 'source': str(Path(__file__).resolve()),
                                            'command': command})
                    break
                except OSError:
                    sock.close()
                    sock = None
            if proc.poll() is not None:
                raise RuntimeError(tr('mpv_exited'))
            time.sleep(.05)
        if conn is None:
            raise RuntimeError(tr('mpv_connect'))
        # Keep mpv paused before loading; loadfile's reply is not load completion.
        startup_command(conn, ['set_property', 'pause', True])
        if startup_command(conn, ['get_property', 'pause']) is not True:
            raise RuntimeError(tr('mpv_pause_unconfirmed'))
        conn.events.clear()
        startup_command(conn, ['loadfile', str(audio), 'replace'])
        conn.wait_event('file-loaded')
        conn.record('mpv-version', startup_command(conn, ['get_property', 'mpv-version']))
        wait_for_audio(conn)
        # Drop the load's playback-restart: only the new seek's event is relevant.
        conn.events.clear()
        startup_command(conn, ['seek', 0, 'absolute+exact'])
        conn.wait_event('seek')
        conn.wait_event('playback-restart')
        last_position, duration = wait_for_audio(conn, near_zero=True)
        conn.record('ready', {'position': last_position, 'duration': duration})
        # Do not start audio until terminal is ready and first frame is drawn.
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        paused = False
        pending = bytearray()
        esc_at = None
        render(text, tokens, matches, last_position, True, duration)
        conn.record('first-frame', {'position': last_position})
        # Check again after terminal setup/rendering, which may take time.
        wait_for_audio(conn, near_zero=True)
        startup_command(conn, ['set_property', 'pause', False])
        conn.record('unpaused', True)
        while True:
            status = conn.command(['get_property', 'time-pos'])
            pos = status.get('data')
            if isinstance(pos, (float, int)):
                last_position = float(pos)
            d = conn.command(['get_property', 'duration']).get('data')
            if isinstance(d, (float, int)):
                duration = float(d)
            # mpv pauses itself at EOF while keeping the file seekable.
            actual_pause = conn.command(['get_property', 'pause']).get('data')
            if isinstance(actual_pause, bool):
                paused = actual_pause
            render(text, tokens, matches, last_position, paused, duration)
            if conn.trace is not None:
                conn.record('first-playing-frame', {'position': last_position, 'duration': duration})
                # Only capture startup; keep the normal playback loop lightweight.
                conn.trace = None
            ready, _, _ = select.select([fd], [], [], .06)
            if ready:
                pending.extend(os.read(fd, 64))
            while pending:
                key, rest = parse_key(pending)
                if key is None:
                    if pending == b'\x1b' and esc_at is None:
                        esc_at = time.monotonic()
                    break
                pending = bytearray(rest)
                esc_at = None
                if key == 'esc':
                    return
                if key == 'space':
                    paused = not paused
                    conn.command(['set_property', 'pause', paused])
                elif key in ('left', 'right'):
                    conn.command(['seek', -5 if key == 'left' else 5, 'relative', 'exact'])
            if pending == b'\x1b' and esc_at is not None and time.monotonic() - esc_at > .2:
                return
    except Exception as exc:
        if conn is not None:
            conn.record('failure', repr(exc))
        raise
    finally:
        if old is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
        if conn:
            conn.close()
        elif sock:
            sock.close()
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if trace is not None:
            trace.close()


def check_voice(language=None, refresh=False):
    """Refresh the catalog if needed, optionally checking a specific voice."""
    if refresh or voices.available is None:
        print_wrapped(tr('voice_checking'), flush=True)
        try:
            asyncio.run(voices.refresh())
        except Exception:
            voices.available = None
            print_wrapped(tr('voice_check_failed'))
            return False
    if language is not None and not voices.supports(language):
        print_wrapped(tr('voice_unavailable', voice=LANGUAGES[language][1],
                 language=tr('language_' + language)))
        return False
    return True


def settings_menu():
    check_voice(refresh=True)
    codes = list(LANGUAGES)
    while True:
        print_wrapped('\n' + tr('settings_title'))
        print_wrapped(tr('current_language', language=tr('language_' + ui.language)))
        for index, code in enumerate(codes, 1):
            status = ('voice_unknown' if voices.available is None else
                      'voice_available' if voices.supports(code) else 'voice_missing')
            marker = '*' if code == ui.language else ' '
            print_wrapped(f' [{index}] {marker} {tr("language_" + code)} - {tr(status)}')
        print_wrapped(' [0] ' + tr('back'))
        choice = input(wrap_message(tr('choice'))).strip()
        if choice == '0':
            return
        clear_terminal()
        if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(codes):
            print_wrapped(tr('invalid_choice'))
            continue
        language = codes[int(choice) - 1]
        if not check_voice(language):
            continue
        previous = ui.language
        try:
            ui.use(language)
        except (OSError, ValueError, UnicodeError):
            print_wrapped(tr('language_resource_failed'))
            continue
        try:
            save_language(language)
        except OSError:
            ui.use(previous)
            print_wrapped(tr('config_write_failed'))
            continue
        print_wrapped(tr('language_changed'))


def main():
    language, notice = load_language()
    try:
        ui.use(language)
    except (OSError, ValueError, UnicodeError):
        ui.use('en')
        notice = 'language_resource_failed'
    for cmd in ('mpv', 'termux-clipboard-get'):
        if shutil.which(cmd) is None:
            clear_terminal()
            if notice:
                print_wrapped(tr(notice))
            print_wrapped(tr('missing_command', command=cmd))
            return
    while True:
        clear_terminal()
        print_wrapped('==========================\n'
              f'       READ DAT v{VERSION}\n'
              f'       {tr("karaoke_mode")}\n'
              '==========================\n' +
              f' [1] {tr("paste_text")}\n'
              f' [2] {tr("read_clipboard")}\n\n'
              f' [8] {tr("settings")}\n'
              f' [0] {tr("exit")}\n')
        if notice:
            print_wrapped(tr(notice))
            notice = None
        try:
            choice = input(wrap_message(tr('choice'))).strip()
            if choice not in ('0', '1', '2', '8'):
                notice = 'invalid_choice'
                continue
            clear_terminal()
            if choice == '0':
                return
            if choice == '8':
                settings_menu()
                continue
            text = paste() if choice == '1' else clipboard()
            if not text.strip():
                print_wrapped(tr('no_text'))
                time.sleep(1.5)
                continue
            if not check_voice(ui.language):
                input(wrap_message(tr('press_enter')))
                continue
            with tempfile.TemporaryDirectory(prefix='read_dat_') as directory:
                audio = Path(directory) / 'voice.mp3'
                socket_path = str(Path(directory) / 'mpv.sock')
                print_wrapped(CLEAR + tr('generating'))
                try:
                    timings = asyncio.run(synthesize(text, audio))
                except Exception as exc:
                    voices.available = None
                    raise RuntimeError(tr('tts_failed')) from exc
                player(text, audio, timings, socket_path)
        except EOFError:
            return
        except KeyboardInterrupt:
            notice = 'returning'
        except Exception as exc:
            print_wrapped(tr('error', details=str(exc)))
            try:
                input(wrap_message(tr('press_enter')))
            except (KeyboardInterrupt, EOFError):
                return


if __name__ == '__main__':
    main()
