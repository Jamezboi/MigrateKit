import json, os, ssl, time, urllib.error, urllib.parse, urllib.request, http.client
from pathlib import Path

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"
API_VERSION = "2026-03-10"
MAX_ASSET = 2 * 1024 * 1024 * 1024


def _headers(token, content_type="application/vnd.github+json"):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "Content-Type": content_type,
        "User-Agent": "MigrateKit/1.2.2",
    }


def _json_request(url, token, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(token), method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload_archive(path: Path, log, status):
    token = os.environ.get("MIGRATEKIT_GITHUB_TOKEN", "").strip()
    repo = os.environ.get("MIGRATEKIT_GITHUB_REPO", "").strip().strip("/")
    if not token or not repo:
        return None
    if path.stat().st_size >= MAX_ASSET:
        raise ValueError("GitHub release assets must be smaller than 2 GiB.")
    if "/" not in repo:
        raise ValueError("MIGRATEKIT_GITHUB_REPO must be owner/repository.")

    owner, name = repo.split("/", 1)
    tag = "migratekit-backups"
    status("Uploading backup to GitHub…")
    log(f"GitHub target: {repo} · asset: {path.name}")

    try:
        release = _json_request(f"{API}/repos/{owner}/{name}/releases/tags/{urllib.parse.quote(tag, safe='')}", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = _json_request(
            f"{API}/repos/{owner}/{name}/releases",
            token,
            method="POST",
            body={
                "tag_name": tag,
                "name": "MigrateKit Backups",
                "body": "MigrateKit migration archives uploaded by the desktop client.",
                "draft": False,
                "prerelease": False,
            },
        )

    assets_url = release["upload_url"].split("{", 1)[0]
    asset_name = f"{int(time.time())}_{path.name}"
    url = assets_url + "?" + urllib.parse.urlencode({"name": asset_name})

    size = path.stat().st_size
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=120)
    try:
        conn.putrequest("POST", parsed.path + ("?" + parsed.query if parsed.query else ""))
        for key, value in _headers(token, "application/octet-stream").items():
            conn.putheader(key, value)
        conn.putheader("Content-Length", str(size))
        conn.endheaders()
        sent = 0
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(8 * 1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)
                sent += len(chunk)
                status(f"Uploading to GitHub… {sent / size:.0%}")
        response = conn.getresponse()
        payload = response.read().decode("utf-8", errors="replace")
        if response.status not in (201,):
            raise RuntimeError(f"GitHub upload failed ({response.status}): {payload[:500]}")
        result = json.loads(payload)
    finally:
        conn.close()

    log(f"GitHub upload complete: {result.get('browser_download_url', asset_name)}")
    status("GitHub upload complete")
    return result.get("browser_download_url")
