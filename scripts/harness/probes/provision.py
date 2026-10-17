"""受信一次性 volume 初始化，仅随机 canary；输出不含凭据。"""

import hashlib
import json
import os
import secrets
from pathlib import Path


def put(path, value, uid):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    os.chown(path, uid, uid)
    path.chmod(0o600)


def main():
    for name, uid in [("state", 10001), ("workspace", 10002), ("human", 10003)]:
        Path("/" + name).mkdir(exist_ok=True)
        os.chown("/" + name, uid, uid)
        os.chmod("/" + name, 0o700)
    callers = []
    for role, directory, uid in [("agent", "workspace", 10002), ("human", "human", 10003)]:
        token = secrets.token_urlsafe(40)
        put(f"/{directory}/token", token, uid)
        callers.append(
            {
                "id": role,
                "role": role,
                "project_ids": ["a" * 32],
                "capabilities": ["project.read", "project.mutate"]
                if role == "agent"
                else ["project.read", "human.write"],
                "expires_at": 4102444800,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "grants": [],
            }
        )
    put(
        "/state/policy.json",
        json.dumps({"version": 2, "external_mutations": True, "callers": callers}),
        10001,
    )
    put("/state/core_canary", secrets.token_urlsafe(40), 10001)
    put("/human/cookie_canary", secrets.token_urlsafe(40), 10003)
    print("CANARY_VOLUMES_READY")


if __name__ == "__main__":
    main()
