import hashlib
import secrets


def hash_password(password: str, iterations: int = 260000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('ascii'), iterations
    ).hex()
    return f'pbkdf2_sha256${iterations}${salt}${digest}'


def verify_password(stored: str, password: str) -> bool:
    try:
        if stored.startswith('pbkdf2_sha256$'):
            algo, iterations, salt, digest = stored.split('$', 3)
            test = hashlib.pbkdf2_hmac(
                'sha256', password.encode('utf-8'), salt.encode('ascii'), int(iterations)
            ).hex()
            return secrets.compare_digest(test, digest)
        if stored.startswith('sha256_salt$'):
            _algo, salt, digest = stored.split('$', 2)
            test = hashlib.sha256(f'{salt}:{password}'.encode('utf-8')).hexdigest()
            return secrets.compare_digest(test, digest)
    except Exception:
        return False
    return False
