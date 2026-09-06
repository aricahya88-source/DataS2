import json
import os
import urllib.error
import urllib.request


class GasAPIError(RuntimeError):
    pass


def _config():
    endpoint = (os.environ.get('GAS_ENDPOINT') or '').strip()
    secret = (os.environ.get('GAS_SECRET') or '').strip()
    timeout = int(os.environ.get('GAS_TIMEOUT_SECONDS', '45'))
    if not endpoint:
        raise GasAPIError('GAS_ENDPOINT belum diatur di Environment Variables.')
    if not secret:
        raise GasAPIError('GAS_SECRET belum diatur di Environment Variables.')
    return endpoint, secret, timeout


def gas_call(action, payload=None, timeout=None):
    endpoint, secret, default_timeout = _config()
    body = {'action': action, 'secret': secret}
    if payload:
        body.update(payload)
    raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        endpoint,
        data=raw,
        method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'SUKA-Share-Peminat/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or default_timeout) as resp:
            text = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace') if exc.fp else str(exc)
        raise GasAPIError(f'Apps Script HTTP {exc.code}: {detail[:500]}') from exc
    except urllib.error.URLError as exc:
        raise GasAPIError(f'Koneksi ke Apps Script gagal: {exc.reason}') from exc
    except TimeoutError as exc:
        raise GasAPIError('Koneksi ke Apps Script melebihi batas waktu.') from exc

    try:
        data = json.loads(text)
    except Exception as exc:
        raise GasAPIError(f'Respons Apps Script bukan JSON: {text[:500]}') from exc

    if not data.get('ok'):
        raise GasAPIError(data.get('error') or 'Apps Script menolak permintaan.')
    return data
