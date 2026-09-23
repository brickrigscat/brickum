import os
import re
import sys
import platform
import json
import html as html_lib
import shutil
import zipfile
import tarfile
import subprocess
import threading
import urllib.request
import webbrowser
import importlib
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pathlib import Path
from datetime import datetime, timezone

# On Windows, force GUI-mode Python so the launcher itself never keeps
# a black console window open, even if .pyw is accidentally associated
# with python.exe instead of pythonw.exe.
if sys.platform.startswith("win"):
    exe_name = Path(sys.executable).name.lower()
    if exe_name == "python.exe":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            subprocess.Popen(
                [str(pythonw), str(Path(__file__).resolve())] + sys.argv[1:],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            sys.exit(0)

APP_ID = "552100"

# Python equivalent of AHK's A_ScriptDir.
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR

INSTANCES_DIR = BASE_DIR / "instantes"
TOOLS_DIR = BASE_DIR / "tools"
DEPOT_DIR = TOOLS_DIR / "DepotDownloader"
CACHE_DIR = BASE_DIR / "steamdb_cache"
HISTORY_FILE = BASE_DIR / "brickum_history.json"
STEAMCMD_DIR = TOOLS_DIR / "steamcmd"

# This is only a DEFAULT. The user can change it in the GUI.
DEFAULT_DEPOT_ID = "552101"


def ensure_dirs():
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        save_history({"app_id": APP_ID, "depots": {}})



def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_history():
    if not HISTORY_FILE.exists():
        return {"app_id": APP_ID, "depots": {}}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        data.setdefault("app_id", APP_ID)
        data.setdefault("depots", {})
        return data
    except Exception:
        return {"app_id": APP_ID, "depots": {}}


def save_history(data):
    HISTORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def remember_manifest(depot_id, manifest_id, source="unknown", branch="unknown", label="", current=None):
    depot_id = str(depot_id).strip()
    manifest_id = str(manifest_id).strip()
    if not depot_id.isdigit() or not manifest_id.isdigit():
        return False
    history = load_history()
    depot = history.setdefault("depots", {}).setdefault(depot_id, {"manifests": []})
    manifests = depot.setdefault("manifests", [])
    now = utc_now()
    item = next((x for x in manifests if str(x.get("manifest")) == manifest_id), None)
    is_new = item is None
    if item is None:
        item = {
            "manifest": manifest_id,
            "first_seen": now,
            "last_seen": now,
            "source": source,
            "branch": branch or "unknown",
            "label": label or "",
            "current": bool(current) if current is not None else False,
        }
        manifests.append(item)
    else:
        item["last_seen"] = now
        if source:
            item["source"] = source
        if branch and branch != "unknown":
            item["branch"] = branch
        if label:
            item["label"] = label
        if current is not None:
            item["current"] = bool(current)
    depot["last_checked"] = now
    save_history(history)
    return is_new


def mark_current_manifest(depot_id, manifest_id, branch="public", source="Steam"):
    remember_manifest(depot_id, manifest_id, source=source, branch=branch, current=True)
    history = load_history()
    depot = history.setdefault("depots", {}).setdefault(str(depot_id), {"manifests": []})
    previous = str(depot.get("current_manifest", ""))
    for item in depot.get("manifests", []):
        item["current"] = str(item.get("manifest")) == str(manifest_id)
    depot["current_manifest"] = str(manifest_id)
    depot["current_branch"] = branch
    depot["last_checked"] = utc_now()
    save_history(history)
    return previous != str(manifest_id)


def history_versions_for_depot(depot_id):
    history = load_history()
    depot = history.get("depots", {}).get(str(depot_id), {})
    items = sorted(depot.get("manifests", []), key=lambda x: x.get("first_seen", ""), reverse=True)
    result = []
    for item in items:
        manifest = str(item.get("manifest", ""))
        if not manifest:
            continue
        label = item.get("label") or f'First seen {item.get("first_seen", "")}'
        branch = item.get("branch", "unknown")
        current = " CURRENT" if item.get("current") else ""
        result.append({
            "name": f"{label} [{branch}]{current}",
            "manifest": manifest,
            "date": item.get("first_seen", ""),
            "branch": branch,
            "source": "Brickum saved history",
            "depot_id": str(depot_id),
        })
    return result


def steamcmd_executable():
    names = ["steamcmd.exe"] if sys.platform.startswith("win") else ["steamcmd.sh", "steamcmd"]
    for name in names:
        matches = list(STEAMCMD_DIR.rglob(name))
        if matches:
            return matches[0]
    found = shutil.which("steamcmd")
    return Path(found) if found else None


def install_steamcmd(status_cb=None):
    exe = steamcmd_executable()
    if exe:
        return exe
    STEAMCMD_DIR.mkdir(parents=True, exist_ok=True)
    if status_cb:
        status_cb("Installing SteamCMD from Valve...")
    if sys.platform.startswith("win"):
        url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
        archive = STEAMCMD_DIR / "steamcmd.zip"
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive, "r") as z:
            z.extractall(STEAMCMD_DIR)
        archive.unlink(missing_ok=True)
    elif sys.platform.startswith("linux"):
        url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
        archive = STEAMCMD_DIR / "steamcmd_linux.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(STEAMCMD_DIR)
        archive.unlink(missing_ok=True)
    else:
        raise RuntimeError("Automatic SteamCMD install currently supports Windows and Linux.")
    exe = steamcmd_executable()
    if not exe:
        raise RuntimeError("SteamCMD was not found after installation.")
    return exe


def query_current_manifest_for_depot(depot_id, username, status_cb=None):
    """
    Ask Steam for the CURRENT public manifest using DepotDownloader itself.

    Important:
    - We intentionally OMIT -manifest. DepotDownloader then resolves the current
      manifest for the public branch from Steam.
    - -manifest-only downloads metadata only, not the whole game.
    - DepotDownloader writes manifest_<depot>_<manifest>.txt, which gives us the
      exact manifest ID without scraping SteamDB.
    """
    depot_id = str(depot_id).strip()
    username = str(username).strip()

    if not depot_id.isdigit():
        raise ValueError("Depot ID must contain only numbers.")
    if not username:
        raise ValueError("Enter your Steam username first.")

    downloader = install_depot_downloader(status_cb or (lambda *_: None))
    if not depot_downloader_works(downloader):
        downloader = install_depot_downloader(
            status_cb or (lambda *_: None),
            force_repair=True,
        )

    check_dir = BASE_DIR / "current_manifest_check" / depot_id
    check_dir.mkdir(parents=True, exist_ok=True)

    # Remove old text dumps so we only read the result from this check.
    for old in check_dir.glob(f"manifest_{depot_id}_*.txt"):
        try:
            old.unlink()
        except Exception:
            pass

    if status_cb:
        status_cb(
            "Checking Steam with DepotDownloader... "
            "A login window may appear for Steam Guard."
        )

    downloader = Path(downloader)

    if downloader.suffix.lower() == ".dll":
        command = ["dotnet", str(downloader)]
    else:
        command = [str(downloader)]

    command += [
        "-app", APP_ID,
        "-depot", depot_id,
        "-username", username,
        "-remember-password",
        "-manifest-only",
        "-dir", str(check_dir),
    ]

    # On Windows we deliberately show a console for this operation because
    # Steam may ask for password / mobile confirmation / Steam Guard.
    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

    process = subprocess.Popen(
        command,
        cwd=str(DEPOT_DIR),
        creationflags=creation_flags,
    )
    exit_code = process.wait()

    if exit_code != 0:
        raise RuntimeError(
            f"DepotDownloader exited with code {exit_code}. "
            "Finish the Steam login/Steam Guard prompt, then try again."
        )

    dumps = sorted(
        check_dir.rglob(f"manifest_{depot_id}_*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not dumps:
        for p in sorted(check_dir.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if not p.is_file():
                continue
            m = re.search(rf"{re.escape(depot_id)}[_\\.-](\\d{{10,20}})", p.name)
            if m:
                return m.group(1)
        raise RuntimeError(
            "Steam login finished, but Brickum could not find the current manifest ID."
        )

    newest = dumps[0]

    # Preferred: parse manifest ID from the filename created by DepotDownloader.
    filename_match = re.fullmatch(
        rf"manifest_{re.escape(depot_id)}_(\d+)\.txt",
        newest.name,
        flags=re.I,
    )
    if filename_match:
        return filename_match.group(1)

    # Fallback: read the manifest ID line inside the text dump.
    content = newest.read_text(encoding="utf-8", errors="ignore")
    inside = re.search(
        r"Manifest ID / date\s*:\s*(\d{10,20})",
        content,
        flags=re.I,
    )
    if inside:
        return inside.group(1)

    raise RuntimeError(
        f"DepotDownloader created {newest.name}, but Brickum could not read its manifest ID."
    )


def safe_instance_name(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip().strip(".")
    return name or "BrickRigs_Instance"


def strip_tags(value):
    value = re.sub(r"<script\b[^>]*>.*?</script>", "", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", "", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def cache_file_for(depot_id):
    return CACHE_DIR / f"depot_{depot_id}.json"


def load_cache(depot_id):
    path = cache_file_for(depot_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_cache(depot_id, versions):
    cache_file_for(depot_id).write_text(
        json.dumps(versions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def steamdb_url_for(depot_id):
    return f"https://steamdb.info/depot/{depot_id}/manifests/"



def parse_steamdb_manifest_page(page, depot_id):
    """
    Parse SteamDB's 'Previously seen manifests' section from either HTML
    or readable text. This deliberately avoids depending on SteamDB's CSS/JS.
    """
    versions = []
    seen = set()

    decoded = html_lib.unescape(page)

    # First isolate the manifest section so we don't accidentally capture
    # unrelated 64-bit numbers elsewhere on the page.
    lower = decoded.lower()
    start = lower.find("previously seen manifests")
    if start != -1:
        section = decoded[start:]
        end_markers = [
            "displaying change",
            "<h2>history",
            "## history",
        ]
        for marker in end_markers:
            pos = section.lower().find(marker.lower())
            if pos > 0:
                section = section[:pos]
                break
    else:
        section = decoded

    # Try row-by-row HTML parsing first.
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", section, flags=re.I | re.S)

    for row in rows:
        row_text = strip_tags(row)
        manifest = None

        # SteamDB links often contain changeid=M:<manifest>.
        m = re.search(r"changeid=M(?:%3A|:)(\d{10,20})", row, flags=re.I)
        if m:
            manifest = m.group(1)

        # Current page also prints the ManifestID directly in the row.
        if not manifest:
            ids = re.findall(r"\b\d{15,20}\b", row_text)
            if ids:
                manifest = ids[-1]

        if not manifest or manifest in seen:
            continue

        seen.add(manifest)

        date_match = re.search(
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+[–-]\s+\d{2}:\d{2}:\d{2}\s+UTC)",
            row_text,
        )
        date_text = date_match.group(1) if date_match else "SteamDB manifest"

        branch = "experimental" if "experimental" in row_text.lower() else "public"

        versions.append({
            "name": f"{date_text} [{branch}]",
            "manifest": manifest,
            "date": date_text,
            "branch": branch,
            "source": "SteamDB live",
            "depot_id": depot_id,
        })

    # Fallback for readable/plain text copies of the page.
    if not versions:
        plain = strip_tags(section)
        lines = [line.strip() for line in re.split(r"[\r\n]+", plain) if line.strip()]

        for line in lines:
            ids = re.findall(r"\b\d{15,20}\b", line)
            if not ids:
                continue

            manifest = ids[-1]
            if manifest in seen:
                continue

            seen.add(manifest)

            date_match = re.search(
                r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+[–-]\s+\d{2}:\d{2}:\d{2}\s+UTC)",
                line,
            )
            date_text = date_match.group(1) if date_match else "SteamDB manifest"
            branch = "experimental" if "experimental" in line.lower() else "public"

            versions.append({
                "name": f"{date_text} [{branch}]",
                "manifest": manifest,
                "date": date_text,
                "branch": branch,
                "source": "SteamDB live",
                "depot_id": depot_id,
            })

    return versions


def fetch_steamdb_versions(depot_id, status_cb=None):
    if not depot_id.isdigit():
        raise ValueError("Depot ID must contain only numbers.")

    url = steamdb_url_for(depot_id)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://steamdb.info/depot/{depot_id}/",
    }

    if status_cb:
        status_cb(f"Reading SteamDB depot {depot_id}...")

    errors = []

    # 1) Direct Python request.
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            page = response.read().decode("utf-8", "ignore")
        versions = parse_steamdb_manifest_page(page, depot_id)
        if versions:
            save_cache(depot_id, versions)
            return versions
        errors.append("Direct request returned no manifest table.")
    except Exception as error:
        errors.append(f"Direct request: {error}")

    # 2) curl fallback. This works on most modern Windows/Linux installs.
    curl = shutil.which("curl")
    if curl:
        try:
            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform.startswith("win")
                else 0
            )
            result = subprocess.run(
                [
                    curl, "-L", "--compressed", "--silent", "--show-error",
                    "--max-time", "25",
                    "-A", headers["User-Agent"],
                    url,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=creation_flags,
            )
            if result.stdout:
                versions = parse_steamdb_manifest_page(result.stdout, depot_id)
                if versions:
                    save_cache(depot_id, versions)
                    return versions
            errors.append("curl returned no manifest table.")
        except Exception as error:
            errors.append(f"curl: {error}")

    raise RuntimeError(" | ".join(errors))



def depot_exe():
    exe = DEPOT_DIR / "DepotDownloader.exe"
    if exe.exists():
        return exe
    matches = list(DEPOT_DIR.rglob("DepotDownloader.exe"))
    return matches[0] if matches else None


def depot_downloader_works(path):
    if not path:
        return False
    try:
        result = subprocess.run(
            [str(path), "--version"],
            cwd=str(Path(path).parent),
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except Exception:
        return False


def install_depot_downloader(status_cb, force_repair=False):
    existing = depot_exe()
    if existing and not force_repair and depot_downloader_works(existing):
        return existing

    if DEPOT_DIR.exists():
        try:
            shutil.rmtree(DEPOT_DIR)
        except Exception:
            pass

    DEPOT_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    status_cb("Installing official DepotDownloader Windows x64...")

    url = (
        "https://github.com/SteamRE/DepotDownloader/releases/download/"
        "DepotDownloader_3.4.0/DepotDownloader-windows-x64.zip"
    )
    zip_path = TOOLS_DIR / "DepotDownloader-windows-x64.zip"

    req = urllib.request.Request(url, headers={"User-Agent": "brickum_launcher"})
    with urllib.request.urlopen(req, timeout=120) as response, open(zip_path, "wb") as f:
        shutil.copyfileobj(response, f)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(DEPOT_DIR)

    zip_path.unlink(missing_ok=True)

    exe = depot_exe()
    if not exe or not depot_downloader_works(exe):
        raise RuntimeError("Official Windows x64 DepotDownloader could not start.")

    status_cb("DepotDownloader Windows x64 is ready.")
    return exe


def build_depot_command(downloader, app_id, depot_id, manifest, username, target):
    downloader = Path(downloader)

    # If we got a DLL, run it through dotnet.
    if downloader.suffix.lower() == ".dll":
        command = [
            "dotnet",
            str(downloader),
        ]
    else:
        command = [str(downloader)]

    command += [
        "-app", app_id,
        "-depot", depot_id,
        "-manifest", manifest,
        "-username", username,
        "-remember-password",
        "-dir", str(target),
    ]

    return command


def open_folder(path):
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_dirs()

        self.title("Brickum Launcher - Brick Rigs Instance Manager")
        self.geometry("940x650")
        self.minsize(820, 560)

        self.depot_id = tk.StringVar(value=DEFAULT_DEPOT_ID)
        self.versions = history_versions_for_depot(self.depot_id.get()) + load_cache(self.depot_id.get())

        self.username = tk.StringVar()
        self.instance_name = tk.StringVar(value="My Brick Rigs")
        self.status = tk.StringVar(value="Starting...")
        self.selected_version = tk.StringVar()

        self.build_ui()
        self.refresh_version_combo()
        self.refresh_instances()

        self.after(250, self.check_steam_current_thread)

    def build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="Brickum Launcher",
            font=("Segoe UI", 19, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            top,
            text="Brick Rigs instances • choose any depot • saves every manifest it sees",
        ).grid(row=1, column=0, sticky="w")

        frm = ttk.LabelFrame(self, text="Create / Install Instance", padding=12)
        frm.pack(fill="x", padx=12, pady=(0, 10))

        ttk.Label(frm, text="Instance name:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.instance_name).grid(
            row=0, column=1, sticky="ew", padx=8
        )

        ttk.Label(frm, text="Steam username:").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(frm, textvariable=self.username).grid(
            row=1, column=1, sticky="ew", padx=8, pady=(8, 0)
        )

        ttk.Label(frm, text="Depot ID:").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

        depot_row = ttk.Frame(frm)
        depot_row.grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))

        ttk.Entry(
            depot_row,
            textvariable=self.depot_id,
            width=18,
        ).pack(side="left")

        ttk.Button(
            depot_row,
            text="Load This Depot",
            command=self.change_depot,
        ).pack(side="left", padx=6)

        ttk.Label(
            depot_row,
            text="Windows default: 552101",
        ).pack(side="left", padx=(8, 0))

        ttk.Label(frm, text="SteamDB version / manifest:").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )

        self.version_combo = ttk.Combobox(
            frm,
            textvariable=self.selected_version,
            state="readonly",
            width=64,
        )
        self.version_combo.grid(
            row=3, column=1, sticky="ew", padx=8, pady=(8, 0)
        )

        buttons = ttk.Frame(frm)
        buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

        ttk.Button(
            buttons,
            text="Install Selected Version",
            command=self.install_clicked,
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="Check Steam Current",
            command=self.check_steam_current_thread,
        ).pack(side="left", padx=6)

        ttk.Button(
            buttons,
            text="Saved History",
            command=self.show_saved_history,
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="Add Manifest Manually",
            command=self.add_manifest,
        ).pack(side="left", padx=6)

        note = ttk.Label(
            frm,
            text=(
                "Note: On first use, Brickum downloads the official DepotDownloader "
                "release from SteamRE's GitHub. Windows Security/antivirus may show a "
                "warning or block the new EXE. Only allow it if the download source is "
                "github.com/SteamRE/DepotDownloader."
            ),
            wraplength=760,
            justify="left",
        )
        note.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        frm.columnconfigure(1, weight=1)

        inst = ttk.LabelFrame(self, text="Installed Instances", padding=12)
        inst.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.tree = ttk.Treeview(
            inst,
            columns=("depot", "manifest", "path"),
            show="tree headings",
            selectmode="browse",
        )

        self.tree.heading("#0", text="Instance")
        self.tree.heading("depot", text="Depot")
        self.tree.heading("manifest", text="Manifest")
        self.tree.heading("path", text="Folder")

        self.tree.column("#0", width=200)
        self.tree.column("depot", width=90)
        self.tree.column("manifest", width=170)
        self.tree.column("path", width=430)

        self.tree.pack(fill="both", expand=True)

        instance_buttons = ttk.Frame(inst)
        instance_buttons.pack(fill="x", pady=(10, 0))

        ttk.Button(
            instance_buttons,
            text="▶ Run",
            command=self.run_instance,
        ).pack(side="left")

        ttk.Button(
            instance_buttons,
            text="Choose Launch File",
            command=self.choose_launch_file,
        ).pack(side="left", padx=6)

        ttk.Button(
            instance_buttons,
            text="Open Folder",
            command=self.open_instance,
        ).pack(side="left")

        ttk.Button(
            instance_buttons,
            text="Refresh",
            command=self.refresh_instances,
        ).pack(side="left", padx=6)

        ttk.Button(
            instance_buttons,
            text="Delete Instance",
            command=self.delete_instance,
        ).pack(side="right")

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")

        ttk.Label(bottom, textvariable=self.status).pack(side="left")

    def set_status(self, text):
        self.after(0, self.status.set, text)

    def change_depot(self):
        depot_id = self.depot_id.get().strip()

        if not depot_id.isdigit():
            messagebox.showerror(
                "Invalid depot",
                "Depot ID should contain only numbers.",
            )
            return

        self.versions = history_versions_for_depot(depot_id) + load_cache(depot_id)
        self.refresh_version_combo()
        self.check_steam_current_thread()

    def refresh_version_combo(self):
        values = []

        for version in self.versions:
            source = version.get("source", "")
            suffix = " • LIVE" if source == "SteamDB live" else ""
            values.append(
                f'{version["name"]} | Manifest {version["manifest"]}{suffix}'
            )

        self.version_combo["values"] = values

        if values:
            self.version_combo.current(0)
        else:
            self.selected_version.set("Load a depot to fetch manifests...")

    def selected_version_data(self):
        index = self.version_combo.current()
        if index < 0 or index >= len(self.versions):
            return None
        return self.versions[index]

    def refresh_manifests_thread(self):
        threading.Thread(
            target=self.refresh_manifests,
            daemon=True,
        ).start()

    def refresh_manifests(self):
        depot_id = self.depot_id.get().strip()

        if not depot_id.isdigit():
            self.set_status("Invalid depot ID.")
            return

        try:
            self.set_status(
                f"Connecting to SteamDB for depot {depot_id}..."
            )

            live_versions = fetch_steamdb_versions(depot_id, self.set_status)
            self.versions = live_versions

            self.after(0, self.refresh_version_combo)

            self.set_status(
                f"Depot {depot_id}: found {len(live_versions)} manifest(s) live."
            )

        except Exception as error:
            cached = load_cache(depot_id)

            if cached:
                self.versions = cached
                self.after(0, self.refresh_version_combo)
                self.set_status(
                    f"SteamDB blocked live reading; using {len(cached)} cached manifest(s) for depot {depot_id}."
                )
            else:
                self.versions = []
                self.after(0, self.refresh_version_combo)
                self.set_status(
                    f"SteamDB blocked automatic reading for depot {depot_id}. Use Open SteamDB or Add Manifest Manually."
                )

            # Do not throw a popup every time SteamDB blocks automated access.
            # Keep the GUI usable and show the problem in the status bar instead.

    def check_steam_current_thread(self):
        threading.Thread(target=self.check_steam_current, daemon=True).start()

    def check_steam_current(self):
        depot_id = self.depot_id.get().strip()
        username = self.username.get().strip()

        if not depot_id.isdigit():
            self.set_status("Invalid depot ID.")
            return

        if not username:
            self.set_status("Enter your Steam username first.")
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Steam username needed",
                    "Enter the Steam username for an account that owns Brick Rigs, "
                    "then click Check Steam Current again."
                ),
            )
            return

        try:
            manifest = query_current_manifest_for_depot(
                depot_id,
                username,
                self.set_status,
            )
            is_new = remember_manifest(depot_id, manifest, source="Steam via DepotDownloader", branch="public",
                                       label=f"First seen {utc_now()}")
            changed = mark_current_manifest(depot_id, manifest, branch="public", source="Steam via DepotDownloader")
            self.versions = history_versions_for_depot(depot_id)
            self.after(0, self.refresh_version_combo)
            if is_new:
                self.set_status(f"NEW manifest saved forever: {manifest}")
            elif changed:
                self.set_status(f"Current manifest changed to {manifest} and was saved.")
            else:
                self.set_status(f"Steam current manifest {manifest} is already saved.")
        except Exception as error:
            self.versions = history_versions_for_depot(depot_id)
            self.after(0, self.refresh_version_combo)
            self.set_status(f"Steam check failed, but saved history is safe: {error}")

    def show_saved_history(self):
        depot_id = self.depot_id.get().strip()
        saved = history_versions_for_depot(depot_id)
        if not saved:
            messagebox.showinfo("Saved History", f"No saved manifests yet for depot {depot_id}.")
            return
        lines = [f'{x["manifest"]}  -  {x["name"]}' for x in saved]
        messagebox.showinfo(f"Saved History - Depot {depot_id}", "\n".join(lines[:40]))

    def open_steamdb(self):
        depot_id = self.depot_id.get().strip()
        if not depot_id.isdigit():
            messagebox.showerror("Invalid depot", "Depot ID should contain only numbers.")
            return
        webbrowser.open(steamdb_url_for(depot_id))

    def add_manifest(self):
        depot_id = self.depot_id.get().strip()

        if not depot_id.isdigit():
            messagebox.showerror(
                "Invalid depot",
                "Enter a valid depot ID first.",
            )
            return

        manifest = simpledialog.askstring(
            "Manifest ID",
            f"Enter a manifest ID for depot {depot_id}:",
        )

        if not manifest:
            return

        manifest = manifest.strip()

        if not manifest.isdigit():
            messagebox.showerror(
                "Invalid manifest",
                "Manifest ID should contain only numbers.",
            )
            return

        name = simpledialog.askstring(
            "Version name",
            "Name this version:",
            initialvalue=f"Manual manifest {manifest}",
        )

        if not name:
            return

        remember_manifest(depot_id, manifest, source="manual", branch="manual", label=name)
        self.versions = history_versions_for_depot(depot_id)
        self.refresh_version_combo()

    def install_clicked(self):
        version = self.selected_version_data()

        if not version:
            messagebox.showerror(
                "No version selected",
                "Pick a manifest first.",
            )
            return

        depot_id = self.depot_id.get().strip()

        if not depot_id.isdigit():
            messagebox.showerror(
                "Invalid depot",
                "Depot ID should contain only numbers.",
            )
            return

        name = safe_instance_name(self.instance_name.get())
        username = self.username.get().strip()

        if not username:
            messagebox.showerror(
                "Steam username needed",
                "Enter the Steam username for an account that owns Brick Rigs.",
            )
            return

        remember_manifest(
            depot_id,
            version["manifest"],
            source=version.get("source", "install"),
            branch=version.get("branch", "unknown"),
            label=version.get("name", ""),
        )

        target = INSTANCES_DIR / name

        # Clean up an empty folder left by older Brickum builds.
        if target.exists() and not any(target.iterdir()):
            try:
                target.rmdir()
            except Exception:
                pass

        if target.exists() and any(target.iterdir()):
            if not messagebox.askyesno(
                "Instance already exists",
                f"{target}\n\nalready contains files. Continue anyway?",
            ):
                return

        threading.Thread(
            target=self.install_instance,
            args=(name, username, depot_id, version),
            daemon=True,
        ).start()

    def install_instance(self, name, username, depot_id, version):
        target = INSTANCES_DIR / name
        staging_root = BASE_DIR / "downloads"
        staging = staging_root / f"{name}.partial"

        try:
            staging_root.mkdir(parents=True, exist_ok=True)

            # Never leave a fake/empty final instance behind.
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)

            downloader = install_depot_downloader(self.set_status)
            if not depot_downloader_works(downloader):
                downloader = install_depot_downloader(
                    self.set_status,
                    force_repair=True,
                )

            manifest = str(version["manifest"]).strip()

            self.set_status(
                f"Downloading depot {depot_id}, manifest {manifest}..."
            )

            command = build_depot_command(
                downloader,
                APP_ID,
                depot_id,
                manifest,
                username,
                staging,
            )

            # Save the exact command, but do NOT save a password.
            try:
                (BASE_DIR / "last_download_command.txt").write_text(
                    subprocess.list2cmdline(command),
                    encoding="utf-8",
                )
            except Exception:
                pass

            # Steam authentication may need a visible console for password/
            # Steam Guard/mobile confirmation.
            creation_flags = (
                getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                if sys.platform.startswith("win")
                else 0
            )

            process = subprocess.Popen(
                command,
                cwd=str(DEPOT_DIR),
                creationflags=creation_flags,
            )

            exit_code = process.wait()

            if exit_code != 0:
                raise RuntimeError(
                    f"DepotDownloader stopped with exit code {exit_code}.\n\n"
                    "Finish any Steam login/Steam Guard prompt in the black "
                    "DepotDownloader window. If it closed, try Install again."
                )

            # Verify that an ACTUAL game download happened.
            all_files = [p for p in staging.rglob("*") if p.is_file()]
            if not all_files:
                raise RuntimeError(
                    "DepotDownloader exited, but downloaded zero files.\n\n"
                    "The final instance was NOT created. Check the Steam login "
                    "window and make sure this account owns Brick Rigs."
                )

            game_exe = staging / "BrickRigs.exe"

            if not game_exe.exists():
                # Keep the partial folder for inspection instead of pretending
                # the install succeeded.
                raise RuntimeError(
                    "Files were downloaded, but BrickRigs.exe is missing.\n\n"
                    f"Partial download kept here:\n{staging}\n\n"
                    "This usually means the selected depot/manifest is not the "
                    "Windows Brick Rigs game depot."
                )

            # Put steam_appid.txt into the completed staging install.
            self.ensure_steam_appid(staging)

            remember_manifest(
                depot_id,
                manifest,
                source="installed",
                branch=version.get("branch", "unknown"),
                label=version.get("name", ""),
            )

            metadata = {
                "instance_name": name,
                "app_id": APP_ID,
                "depot_id": depot_id,
                "manifest": manifest,
                "version_name": version.get("name", ""),
                "version_date": version.get("date", ""),
                "branch": version.get("branch", ""),
                "launch_file": "BrickRigs.exe",
            }

            (staging / "brickum_instance.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Only now does the real instance folder appear.
            if target.exists():
                shutil.rmtree(target)

            shutil.move(str(staging), str(target))

            self.set_status(
                f"Installed {name} successfully — {len(all_files)} files."
            )

            self.after(0, self.refresh_instances)

            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Install complete",
                    f"{name} is ready.\n\n"
                    f"Depot: {depot_id}\n"
                    f"Manifest: {manifest}\n\n"
                    f"Installed to:\n{target}\n\n"
                    "BrickRigs.exe was verified and steam_appid.txt was created."
                ),
            )

        except PermissionError as error:
            self.set_status("Install failed: Windows blocked DepotDownloader.")
            self.after(
                0,
                lambda: messagebox.showerror(
                    "Windows blocked DepotDownloader",
                    "Windows denied permission to run DepotDownloader.exe.\n\n"
                    "Brickum downloads it from the official SteamRE GitHub release. "
                    "Check Windows Security / antivirus history and only allow it if "
                    "the file source is github.com/SteamRE/DepotDownloader.\n\n"
                    "You can also right-click DepotDownloader.exe → Properties and "
                    "check whether Windows shows an Unblock option."
                ),
            )
            return

        except Exception as error:
            self.set_status(f"Install failed: {error}")

            # Remove an empty partial folder, but preserve a partial download
            # containing files so it can be inspected/resumed manually.
            try:
                if staging.exists() and not any(staging.rglob("*")):
                    shutil.rmtree(staging, ignore_errors=True)
            except Exception:
                pass

            self.after(
                0,
                lambda err=str(error): messagebox.showerror(
                    "Installation failed",
                    err,
                ),
            )

    def ensure_steam_appid(self, folder):
        appid_path = (
            folder
            / "BrickRigs"
            / "Binaries"
            / "Win64"
            / "steam_appid.txt"
        )

        appid_path.parent.mkdir(parents=True, exist_ok=True)
        appid_path.write_text(APP_ID + "\n", encoding="ascii")

    def detect_launch_file(self, folder):
        # Windows Brick Rigs
        win_exe = folder / "BrickRigs.exe"
        if win_exe.exists():
            return win_exe

        # Common Linux possibilities.
        candidates = [
            folder / "BrickRigs",
            folder / "BrickRigs.sh",
            folder / "start.sh",
            folder / "run.sh",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        # Last resort: executable file in root.
        if not sys.platform.startswith("win"):
            for candidate in folder.iterdir():
                try:
                    if candidate.is_file() and os.access(candidate, os.X_OK):
                        return candidate
                except Exception:
                    pass

        return None

    def read_metadata(self, folder):
        meta_path = folder / "brickum_instance.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_metadata(self, folder, metadata):
        (folder / "brickum_instance.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def refresh_instances(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        INSTANCES_DIR.mkdir(parents=True, exist_ok=True)

        for folder in sorted(INSTANCES_DIR.iterdir()):
            if not folder.is_dir():
                continue

            metadata = self.read_metadata(folder)
            depot = metadata.get("depot_id", "?")
            manifest = metadata.get("manifest", "?")

            launch_file = self.get_launch_file(folder, metadata)
            label = folder.name + (" ✓" if launch_file else " (choose launch file)")

            self.tree.insert(
                "",
                "end",
                iid=str(folder),
                text=label,
                values=(depot, manifest, str(folder)),
            )

    def selected_instance(self):
        selected = self.tree.selection()

        if not selected:
            messagebox.showinfo(
                "Pick an instance",
                "Click an installed instance first.",
            )
            return None

        return Path(selected[0])

    def get_launch_file(self, folder, metadata=None):
        if metadata is None:
            metadata = self.read_metadata(folder)

        saved = metadata.get("launch_file", "")
        if saved:
            candidate = folder / saved
            if candidate.exists():
                return candidate

        return self.detect_launch_file(folder)

    def choose_launch_file(self):
        folder = self.selected_instance()
        if not folder:
            return

        chosen = filedialog.askopenfilename(
            title="Choose the file Brickum should launch",
            initialdir=str(folder),
        )

        if not chosen:
            return

        chosen_path = Path(chosen)

        try:
            relative = chosen_path.relative_to(folder)
        except ValueError:
            messagebox.showerror(
                "Wrong folder",
                "The launch file must be inside this instance folder.",
            )
            return

        metadata = self.read_metadata(folder)
        metadata["launch_file"] = str(relative)
        self.save_metadata(folder, metadata)

        self.refresh_instances()

    def run_instance(self):
        folder = self.selected_instance()
        if not folder:
            return

        metadata = self.read_metadata(folder)
        launch_file = self.get_launch_file(folder, metadata)

        if not launch_file:
            messagebox.showerror(
                "No launch file",
                "Brickum could not find a launch file.\n\n"
                "Use 'Choose Launch File' first.",
            )
            return

        self.ensure_steam_appid(folder)

        try:
            subprocess.Popen(
                [str(launch_file)],
                cwd=str(folder),
            )
            self.status.set(f"Running {folder.name}...")
        except PermissionError:
            messagebox.showerror(
                "Permission denied",
                "The launch file is not executable.\n\n"
                "On Linux, you may need to run:\n"
                f"chmod +x \"{launch_file}\"",
            )
        except Exception as error:
            messagebox.showerror(
                "Launch failed",
                str(error),
            )

    def open_instance(self):
        folder = self.selected_instance()
        if folder:
            open_folder(folder)

    def delete_instance(self):
        folder = self.selected_instance()

        if not folder:
            return

        if not messagebox.askyesno(
            "Delete instance?",
            f"This permanently deletes:\n\n{folder}\n\nContinue?",
        ):
            return

        try:
            shutil.rmtree(folder)
            self.refresh_instances()
            self.status.set("Instance deleted.")
        except Exception as error:
            messagebox.showerror(
                "Delete failed",
                str(error),
            )


if __name__ == "__main__":
    App().mainloop()
