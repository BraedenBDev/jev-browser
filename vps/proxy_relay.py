#!/usr/bin/env python3
"""Tiny local authenticating proxy relay.

Chromium's --proxy-server cannot carry inline credentials, so Chromium points at this relay
on 127.0.0.1 and the relay forwards to the upstream residential proxy (IPRoyal) with
Proxy-Authorization. The upstream URL is read from the browser-automation vault at startup
(never a plaintext file or systemd unit), unless JEV_PROXY_UPSTREAM overrides it for testing.

Listen port: JEV_PROXY_PORT (default 13128). Upstream: JEV_PROXY_UPSTREAM, else vault key
'iproyal-proxy' (format http://user:pass@host:port).

SECURITY: this binds 127.0.0.1 with NO auth, so it is an open proxy to any LOCAL process,
which can then route through the paid residential proxy as the user's residential IP without
seeing the credentials. Loopback-only limits this to local processes; the real fix is the
same fail-closed cgroup/netns scoping pending for the egress boundary (so only the Chromium
process can reach this port). See docs/learnings.md "VPS Chromium security posture".

Run the self-test with no network:  python3 proxy_relay.py --selftest
"""
import asyncio
import base64
import os
import subprocess
import sys
from urllib.parse import unquote, urlparse

PORT = int(os.environ.get("JEV_PROXY_PORT", "13128"))
VAULT = os.path.expanduser("~/.hermes/secrets/vault.py")
VAULT_PYTHON = os.environ.get("JEV_VAULT_PYTHON", "python3")  # a python with cryptography/Fernet
VAULT_KEY = "iproyal-proxy"


def load_upstream():
    url = os.environ.get("JEV_PROXY_UPSTREAM")
    if not url:
        # Shell out to the vault CLI (decoupled from this process's venv). Its stdout is the
        # secret and stays in memory here; it is never written to a file or argv.
        url = subprocess.run([VAULT_PYTHON, VAULT, "get", VAULT_KEY],
                             capture_output=True, text=True, check=True).stdout.strip()
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname or not u.port:
        raise SystemExit("upstream must be http://user:pass@host:port")
    user, pw = unquote(u.username or ""), unquote(u.password or "")  # urlparse does not decode these
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return u.hostname, u.port, f"Proxy-Authorization: Basic {auth}\r\n"


def connect_request(host_port, auth_header):
    """The CONNECT line + headers we send to the upstream proxy. Pure, for the self-test."""
    return f"CONNECT {host_port} HTTP/1.1\r\nHost: {host_port}\r\n{auth_header}\r\n".encode()


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def handle(client_r, client_w, up_host, up_port, auth_header):
    try:
        line = await client_r.readline()
        if not line:
            client_w.close(); return
        parts = line.split()
        if len(parts) < 2:
            client_w.close(); return
        method, target = parts[0].decode(errors="replace"), parts[1].decode(errors="replace")
        # drain the client's remaining request headers
        headers = b""
        while True:
            h = await client_r.readline()
            headers += h
            if h in (b"\r\n", b"\n", b""):
                break
        up_r, up_w = await asyncio.open_connection(up_host, up_port)
        if method.upper() == "CONNECT":
            up_w.write(connect_request(target, auth_header))
            await up_w.drain()
            status = await up_r.readline()
            rest = b""
            while True:
                h = await up_r.readline()
                rest += h
                if h in (b"\r\n", b"\n", b""):
                    break
            if b" 200" not in status:
                client_w.write(status + rest); await client_w.drain()
                client_w.close(); up_w.close(); return
            client_w.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await client_w.drain()
        else:
            # absolute-URI HTTP request: forward to upstream proxy with auth injected
            up_w.write(line + auth_header.encode() + headers)
            await up_w.drain()
        await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))
    except Exception:
        try:
            client_w.close()
        except Exception:
            pass


async def main():
    up_host, up_port, auth_header = load_upstream()
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, up_host, up_port, auth_header), "127.0.0.1", PORT)
    print(f"relay on 127.0.0.1:{PORT} -> {up_host}:{up_port}", flush=True)
    async with server:
        await server.serve_forever()


def selftest():
    os.environ["JEV_PROXY_UPSTREAM"] = "http://user:p%40ss@geo.example.com:12321"
    host, port, auth = load_upstream()
    assert (host, port) == ("geo.example.com", 12321), (host, port)
    # user:p@ss (password percent-decoded by urlparse) base64 == dXNlcjpwQHNz... check decode
    import base64 as b64
    decoded = b64.b64decode(auth.split("Basic ")[1].strip()).decode()
    assert decoded == "user:p@ss", decoded
    req = connect_request("www.idealista.com:443", auth)
    assert req.startswith(b"CONNECT www.idealista.com:443 HTTP/1.1\r\n")
    assert b"Proxy-Authorization: Basic " in req and req.endswith(b"\r\n\r\n")
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        asyncio.run(main())
