"""Builds a throwaway Manifest V3 extension that answers the proxy auth prompt.

Chrome cannot take credentials on ``--proxy-server``; it pops a native auth dialog
that WebDriver cannot touch. The classic workaround is a tiny extension. Routing
still comes from ``--proxy-server`` (so nothing leaks before the service worker
wakes up) -- this extension only supplies the username/password.

MV2 is dead in current Chrome, so this is MV3: ``webRequestAuthProvider`` plus an
``asyncBlocking`` ``onAuthRequired`` listener.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

_MANIFEST = {
    "manifest_version": 3,
    "name": "Proxy Auth",
    "version": "1.0.0",
    "description": "Supplies credentials for the upstream rotating proxy.",
    "permissions": ["webRequest", "webRequestAuthProvider"],
    "host_permissions": ["<all_urls>"],
    "background": {"service_worker": "background.js"},
    "minimum_chrome_version": "108",
}

_BACKGROUND = """\
const CREDENTIALS = %s;

// Fires when the upstream proxy answers 407. Registered at top level so Chrome
// can wake the service worker for the event after it has gone idle.
chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {
    if (!details.isProxy) {
      callback({});
      return;
    }
    callback({ authCredentials: CREDENTIALS });
  },
  { urls: ["<all_urls>"] },
  ["asyncBlocking"]
);
"""


def build(username: str, password: str, parent: str | Path | None = None) -> Path:
    """Write the unpacked extension and return its directory."""
    root = Path(tempfile.mkdtemp(prefix="proxyauth-", dir=str(parent) if parent else None))

    (root / "manifest.json").write_text(
        json.dumps(_MANIFEST, indent=2), encoding="utf-8"
    )
    (root / "background.js").write_text(
        _BACKGROUND % json.dumps({"username": username, "password": password}),
        encoding="utf-8",
    )
    return root
