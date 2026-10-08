"""Verify missing bindings fail in real local workerd, without deploying."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
NODE = "/home/ats030/.nvm/versions/node/v24.19.0/bin/node"
WRANGLER = "/tmp/cloudflare-migration-tools/node_modules/wrangler/bin/wrangler.js"


def check_startup():
    for missing, message in (
        ("secret", "IKIMONO_SESSION_SECRET binding is required"),
        ("db", "DB binding is required"),
    ):
        config = json.loads((HERE / "wrangler.jsonc").read_text())
        if missing == "secret":
            del config["vars"]["IKIMONO_SESSION_SECRET"]
        else:
            del config["d1_databases"]
        with tempfile.TemporaryDirectory(prefix=".startup-", dir=HERE) as temporary:
            config["main"] = str(HERE / "src" / "worker.py")
            config["base_dir"] = str(HERE / "src")
            # Wrangler locates python_modules beside the selected config.
            (Path(temporary) / "python_modules").symlink_to(HERE / "python_modules", target_is_directory=True)
            (Path(temporary) / "pyproject.toml").symlink_to(HERE / "pyproject.toml")
            (Path(temporary) / "pylock.toml").symlink_to(HERE / "pylock.toml")
            for database in config.get("d1_databases", []):
                database["migrations_dir"] = str(HERE.parent / "cloudflare" / "migrations")
            path = Path(temporary) / "wrangler.jsonc"
            path.write_text(json.dumps(config))
            log = Path(temporary) / "output.log"
            with log.open("w") as output:
                process = subprocess.Popen(
                    [NODE, WRANGLER, "dev", "--config", str(path), "--port", "8794"],
                    cwd=HERE, stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env={**{key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ},
                         "WRANGLER_SEND_METRICS": "false",
                         "IKIMONO_SESSION_SECRET": "synthetic-inherited-must-not-be-used"},
                )
                try:
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        text = log.read_text(errors="replace")
                        if message in text:
                            print(f"PASS: missing {missing} rejected by local workerd", flush=True)
                            break
                        if process.poll() is not None:
                            raise AssertionError(text[-4000:])
                        time.sleep(0.25)
                    else:
                        raise AssertionError(log.read_text(errors="replace")[-4000:])
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == "__main__":
    check_startup()
