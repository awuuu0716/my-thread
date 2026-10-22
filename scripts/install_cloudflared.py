"""Install a verified Windows tunnel helper into this project's .tools directory."""
import hashlib
from pathlib import Path

import httpx


def main():
    target = Path(__file__).resolve().parents[1] / ".tools" / "cloudflared.exe"
    with httpx.Client(follow_redirects=True, timeout=90) as client:
        release = client.get("https://api.github.com/repos/cloudflare/cloudflared/releases/latest")
        release.raise_for_status()
        data = release.json()
        asset = next(a for a in data["assets"] if a["name"] == "cloudflared-windows-amd64.exe")
        digest = asset.get("digest", "")
        if not digest.startswith("sha256:"):
            raise RuntimeError("Official release has no SHA-256 digest; refusing unverified download.")
        response = client.get(asset["browser_download_url"])
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != digest.removeprefix("sha256:"):
            raise RuntimeError("SHA-256 verification failed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        print(f"Installed cloudflared {data['tag_name']} (SHA-256 verified): {target}")


if __name__ == "__main__":
    main()
