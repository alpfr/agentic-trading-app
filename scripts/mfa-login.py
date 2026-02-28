#!/usr/bin/env python3
"""
MFA Login helper — computes TOTP and logs in automatically.
Usage: python3 scripts/mfa-login.py
"""
import urllib.request, json, hmac, hashlib, time, struct, base64, os

BASE     = os.getenv("API_BASE", "https://agentictradepulse.opssightai.com")
USERNAME = os.getenv("ADMIN_USERNAME", "admin")
PASSWORD = os.getenv("ADMIN_PASSWORD", "MyStr0ngPassw0rd")
SECRET   = os.getenv("ADMIN_TOTP_SECRET", "6T3V24WDRWDNXZGLQIZEQANNOPCDKDQU")

def totp(secret: str) -> str:
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    counter = struct.pack(">Q", int(time.time()) // 30)
    mac = hmac.new(key, counter, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[offset:offset+4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)

def post(path, body):
    req = urllib.request.Request(f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

code = totp(SECRET)
print(f"TOTP: {code}")

login = post("/api/auth/login", {"username": USERNAME, "password": PASSWORD})
if "session_token" not in login:
    print(f"Login failed: {login}"); exit(1)

result = post("/api/auth/mfa/verify", {"session_token": login["session_token"], "totp_code": code})
if "access_token" in result:
    print(f"✅ Login successful!")
    print(f"Access token: {result['access_token'][:40]}...")
    print(f"Expires in:   {result['expires_in']}s")
else:
    print(f"MFA failed: {result}")
