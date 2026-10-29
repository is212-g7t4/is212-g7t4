"""SCRUM-8: a local stand-in for Supabase's JWKS, so harness-started services verify real tokens."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

JWKS_PATH = "/auth/v1/.well-known/jwks.json"


class TokenIssuer:
    """Serve a throwaway ES256 public key at SUPABASE_URL's JWKS path and sign tokens with it."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key()))
        body = json.dumps({"keys": [{**jwk, "kid": "e2e", "alg": "ES256", "use": "sig"}]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == JWKS_PATH else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def token(self, user_id, role):
        claims = {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600, "user_role": role}
        return jwt.encode(claims, self.key, algorithm="ES256", headers={"kid": "e2e"})

    def bearer(self, user_id, role):
        return {"Authorization": f"Bearer {self.token(user_id, role)}"}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
