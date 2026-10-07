"""LAN pairing is authorization over HTTP, not transport encryption."""
from collections import defaultdict, deque
import hashlib
import ipaddress
import secrets
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4
from fastapi import HTTPException

COOKIE = "vision_client"


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Security:
    def __init__(self, repository, admin_secret=None):
        self.repository = repository
        self.admin_secret = admin_secret or secrets.token_urlsafe(32)
        self.tokens = {}
        self.rates = defaultdict(deque)
        self.guard = threading.Lock()

    def rate(self, key, maximum):
        with self.guard:
            now = time.monotonic()
            queue = self.rates[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= maximum:
                raise HTTPException(429, "rate_limit", headers={"Retry-After": str(max(1,int(60-now+queue[0])))})
            queue.append(now)
            if len(self.rates) > 4096:
                for old in list(self.rates):
                    if not self.rates[old] or self.rates[old][-1] < now-60:
                        del self.rates[old]

    def identity(self, request):
        bearer = request.headers.get('authorization', '')
        if bearer.startswith('Bearer ') and secrets.compare_digest(bearer[7:], self.admin_secret):
            try:
                loopback = ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                loopback = False
            if loopback:
                return 'admin'
        credential = request.cookies.get(COOKIE)
        client = self.repository.client(digest(credential)) if credential else None
        if client:
            return client['id']
        raise HTTPException(401, 'pairing_required')

    def admin(self, request):
        if self.identity(request) != 'admin':
            raise HTTPException(403, 'admin_required')

    def pairing(self):
        token = secrets.token_urlsafe(32)
        with self.guard:
            self.tokens = {k:v for k,v in self.tokens.items() if v > time.time()}
            self.tokens[digest(token)] = time.time() + 120
        return token

    def exchange(self, token, ip, name='iPhone'):
        self.rate(('pairing',ip), 5)
        with self.guard:
            expires = self.tokens.get(digest(token),0)
            if expires <= time.time():
                raise HTTPException(401,'pairing_expired')
            credential = secrets.token_urlsafe(32)
            identifier = str(uuid4())
            self.repository.add_client(identifier, digest(credential), time.time()+30*86400, name[:80])
            del self.tokens[digest(token)]
            return identifier, credential


def allowed_authority(value, port, addresses):
    try:
        parsed = urlparse('http://' + value)
        return (parsed.hostname in {'127.0.0.1','localhost','::1',*addresses}
                and (parsed.port or 80) == port and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment)
    except ValueError:
        return False
