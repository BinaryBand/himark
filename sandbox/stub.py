"""Stub engine process — seam test for the subprocess protocol.

Reads a JSON pipeline from stdin, returns the target text unchanged.
No VM logic: the point is to prove the JSON protocol and subprocess
wiring work end-to-end before a real engine (Rust, Go, …) is plugged in.

stdin:  {"pipeline": [[step, ...], ...], "target": "..."}
stdout: {"result": "..."} | {"error": "..."}
"""

import json
import sys


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        print(json.dumps({"result": payload["target"]}))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
