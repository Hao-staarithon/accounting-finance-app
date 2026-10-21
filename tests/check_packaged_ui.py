"""Run all transaction-table interactions against an isolated packaged program."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request

import check_table_ui as checks


class PackagedServer:
    def __init__(self, *_args, exe, **_kwargs):
        sandbox = Path(checks.bill_app.DB_PATH).parent
        self.copied = sandbox / "BillAnalyzer" / "bill_data.db"
        self.copied.parent.mkdir()
        source = sqlite3.connect(checks.bill_app.DB_PATH)
        destination = sqlite3.connect(self.copied)
        source.backup(destination)
        destination.close()
        source.close()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            debug_port = probe.getsockname()[1]
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(sandbox)
        environment["QTWEBENGINE_REMOTE_DEBUGGING"] = str(debug_port)
        for name in ("QTWEBENGINE_CHROMIUM_FLAGS", "QT_OPENGL", "QT_QUICK_BACKEND"):
            environment.pop(name, None)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        self.process = subprocess.Popen(
            [str(exe)], env=environment, startupinfo=startup,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Packaged application exited")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=0.5) as response:
                        pages = json.load(response)
                    page = next((page for page in pages if page.get("url", "").startswith("http://127.0.0.1:")), None)
                    if page:
                        self.server_port = urllib.parse.urlparse(page["url"]).port
                        with urllib.request.urlopen(f"http://127.0.0.1:{self.server_port}/api/health", timeout=1) as response:
                            if Path(json.load(response)["db"]) != self.copied:
                                raise RuntimeError("Packaged program is using an unexpected database")
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Packaged program did not start")
        except Exception:
            self.shutdown()
            raise

    def serve_forever(self):
        pass

    def shutdown(self):
        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        self.process.wait(timeout=15)
        time.sleep(1)
        connection = sqlite3.connect(self.copied)
        try:
            assert connection.execute("SELECT count(*) FROM transactions").fetchone()[0] == 6
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path(__file__).resolve().parent.parent / "output" / "dist" / "每笔有数.exe")
    options = parser.parse_args()
    if not options.exe.is_file():
        parser.error("Build the desktop program first or pass --exe PATH")
    checks.make_server = lambda *args, **kwargs: PackagedServer(*args, exe=options.exe.resolve(), **kwargs)
    checks.main()
    print("Packaged application: every table passed UI and batch checks.", flush=True)


if __name__ == "__main__":
    main()
