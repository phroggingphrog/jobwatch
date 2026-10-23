"""Receive standard chat file parts without depending on a frontend's file store.

Originals stay private. Receipt is distinct from readable canonical evidence; an
unknown or corrupt format never becomes profile facts or an instruction source.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path

from fastapi import HTTPException

from jobwatch import users
from jobwatch.candidate import intake


def decode(parts):
    """Validate the entire turn before writing. Never fetch a model/client URL."""
    files, total = [], 0
    for index, part in enumerate(parts, 1):
        if part.get('type') == 'text' and isinstance(part.get('text'), str):
            continue
        spec = part.get('file') if part.get('type') == 'file' else None
        if part.get('type') in ('image_url', 'video_url'):
            source = part.get(part['type'])
            url = source.get('url') if isinstance(source, dict) else source
            mime = re.match(r'data:([A-Za-z0-9.+/-]+);base64,', url or '') if isinstance(url, str) else None
            suffix = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
                      'image/gif': 'gif', 'video/mp4': 'mp4', 'video/webm': 'webm'}.get(mime[1] if mime else '', 'bin')
            spec = {'filename': f'attachment-{index}.{suffix}', 'file_data': url}
        if part.get('type') == 'input_audio':
            audio = part.get('input_audio')
            if isinstance(audio, dict) and audio.get('format') in ('wav', 'mp3') and isinstance(audio.get('data'), str):
                suffix = audio['format']
                spec = {'filename': f'attachment-{index}.{suffix}',
                        'file_data': f'data:audio/{suffix};base64,' + audio['data']}
        if not isinstance(spec, dict):
            raise HTTPException(422, 'invalid_file_content')
        name, data = spec.get('filename'), spec.get('file_data')
        if (not isinstance(name, str) or not 1 <= len(name) <= 240
                or name in ('.', '..') or re.search(r'[/\\\x00-\x1f\x7f]', name)
                or not isinstance(data, str)):
            raise HTTPException(422, 'invalid_file_content')
        match = re.fullmatch(r'data:[A-Za-z0-9.+/-]+;base64,([A-Za-z0-9+/=\r\n]*)', data)
        if not match:
            raise HTTPException(422, 'invalid_file_content')
        try:
            raw = base64.b64decode(match[1].replace('\r', '').replace('\n', ''), validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'invalid_file_content') from None
        total += len(raw)
        if total > intake.MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'too_large')
        files.append((name, raw))
        if len(files) > 20:
            raise HTTPException(422, 'too_many_files')
    return files


def receive(person, files):
    receipts, ids = [], []
    with users.use(person):
        root = users.user_dir(person) / 'chat-uploads'
        for name, raw in files:
            sha = hashlib.sha256(raw).hexdigest()
            # Use the digest as the storage path, never a client filename/extension.
            intake._write_private(root / sha, raw)
            receipt = {'filename': name, 'sha256': sha, 'bytes': len(raw), 'readable': False,
                       'reason': 'unsupported_reading'}
            if Path(name).suffix.lower() in intake.EXTENSIONS:
                try:
                    info = intake.save_upload(person, name, raw, 'evidence')
                    if not intake._load_docs(person, [info['upload_id']])[0]:
                        raise intake.IntakeError('no_extractable_text')
                    ids.append(info['upload_id'])
                    receipt.update(readable=True, upload_id=info['upload_id'], reason='')
                except intake.IntakeError as exc:
                    receipt['reason'] = exc.code
            intake._write_private(root / (sha + '.json'), json.dumps(receipt).encode())
            receipts.append(receipt)
    return ids, receipts
