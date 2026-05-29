import re
import os
import json
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

from mod_parser import ModInfo, ModDependency

MODRINTH_API = "https://api.modrinth.com/v2"
_HEADERS = {"User-Agent": "ModWarden/1.0"}

LOADER_MAP = {
    "forge": "forge",
    "fabric": "fabric",
    "neoforge": "neoforge",
    "quilt": "quilt",
}

LOADER_COMPAT = {
    ("quilt", "fabric"),
}


@dataclass
class CheckResult:
    mod_info: ModInfo
    status: str = "OK"
    issues: List[str] = field(default_factory=list)
    update_info: Optional[dict] = None


def check_mods(
    mods: List[ModInfo],
    target_mc: str,
    target_loader: str,
) -> List[CheckResult]:
    all_ids = {m.mod_id for m in mods if m.mod_id}
    results = []

    duplicates: dict = {}
    for m in mods:
        if m.mod_id:
            duplicates.setdefault(m.mod_id, []).append(m)

    for mod in mods:
        r = CheckResult(mod_info=mod)

        if not mod.is_valid:
            r.status = "ERROR"
            r.issues.append(f"Broken file: {mod.error}")
            results.append(r)
            continue

        loader_ok = _check_loader(mod.loader, target_loader)
        if loader_ok is False:
            r.status = "ERROR"
            r.issues.append(
                f"Wrong loader: mod is for {mod.loader.upper()}, pack uses {target_loader.upper()}"
            )
        elif mod.loader == "unknown":
            _set_warn(r)
            r.issues.append("Cannot detect mod loader (no manifest found)")

        if mod.mc_version_range and mod.mc_version_range not in ("*", ""):
            compat = _version_compatible(target_mc, mod.mc_version_range)
            if compat is False:
                r.status = "ERROR"
                r.issues.append(
                    f"MC version mismatch: mod requires {mod.mc_version_range}, pack is {target_mc}"
                )
            elif compat is None:
                _set_warn(r)
                r.issues.append(f"Cannot verify MC range: {mod.mc_version_range}")

        for dep in mod.dependencies:
            if dep.mandatory and dep.mod_id not in all_ids:
                _set_warn(r)
                r.issues.append(f"Missing dependency: {dep.mod_id}")

        if mod.mod_id and len(duplicates.get(mod.mod_id, [])) > 1:
            _set_warn(r)
            r.issues.append("Duplicate mod ID detected in folder")

        results.append(r)

    return results


def find_update_async(
    mod_info: ModInfo,
    target_mc: str,
    target_loader: str,
    callback: Callable[[Optional[dict]], None],
) -> None:
    def _run():
        result = find_update(mod_info, target_mc, target_loader)
        callback(result)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def find_update(
    mod_info: ModInfo,
    target_mc: str,
    target_loader: str,
) -> Optional[dict]:
    if not REQUESTS_OK:
        return None

    loader = target_loader.lower()
    try:
        slug = mod_info.mod_id
        resp = requests.get(f"{MODRINTH_API}/project/{slug}", headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            if mod_info.name and mod_info.name != mod_info.file_name:
                resp = requests.get(
                    f"{MODRINTH_API}/search",
                    params={"query": mod_info.name, "limit": 1},
                    headers=_HEADERS,
                    timeout=10,
                )
                if resp.status_code == 200:
                    hits = resp.json().get("hits", [])
                    if hits:
                        slug = hits[0]["slug"]
                    else:
                        return None
                else:
                    return None
            else:
                return None

        versions_resp = requests.get(
            f"{MODRINTH_API}/project/{slug}/version",
            params={
                "game_versions": json.dumps([target_mc]),
                "loaders": json.dumps([loader]),
            },
            headers=_HEADERS,
            timeout=10,
        )
        if versions_resp.status_code != 200:
            return None

        versions = versions_resp.json()
        if not versions:
            return None

        latest = versions[0]
        latest["_project_slug"] = slug

        if mod_info.version and latest.get("version_number"):
            if _compare_versions(mod_info.version, latest["version_number"]) >= 0:
                return None

        return latest

    except Exception:
        return None


def download_update(
    version_info: dict,
    mods_folder: str,
    old_jar_path: str,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> Optional[str]:
    if not REQUESTS_OK:
        return None

    files = version_info.get("files", [])
    if not files:
        return None

    primary = next((f for f in files if f.get("primary")), files[0])
    url = primary["url"]
    filename = primary["filename"]
    dest = os.path.join(mods_folder, filename)

    try:
        resp = requests.get(url, stream=True, headers=_HEADERS, timeout=60)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    progress_cb(int(downloaded * 100 / total))

        if old_jar_path and os.path.abspath(old_jar_path) != os.path.abspath(dest):
            os.remove(old_jar_path)

        return dest
    except Exception:
        if os.path.exists(dest):
            os.remove(dest)
        return None


def _check_loader(mod_loader: str, target_loader: str) -> Optional[bool]:
    ml = mod_loader.lower()
    tl = target_loader.lower()
    if ml == "unknown":
        return None
    if ml == tl:
        return True
    if (tl, ml) in LOADER_COMPAT:
        return True
    return False


def _set_warn(result: CheckResult) -> None:
    if result.status == "OK":
        result.status = "WARNING"


def _version_compatible(target: str, version_range: str) -> Optional[bool]:
    tv = _parse_version(target)
    if tv is None:
        return None

    vr = version_range.strip()

    maven = re.match(r"^([\[\(])([^,]*),([^,]*)([\]\)])$", vr)
    if maven:
        low_inc = maven.group(1) == "["
        up_inc = maven.group(4) == "]"
        low_s = maven.group(2).strip()
        up_s = maven.group(3).strip()

        if low_s:
            lv = _parse_version(low_s)
            if lv:
                if (low_inc and tv < lv) or (not low_inc and tv <= lv):
                    return False

        if up_s:
            uv = _parse_version(up_s)
            if uv:
                if (up_inc and tv > uv) or (not up_inc and tv >= uv):
                    return False

        return True

    if re.match(r"^[\d.]+$", vr):
        rv = _parse_version(vr)
        if rv:
            return tv[:2] == rv[:2]
        return None

    parts = re.findall(r"([><=!^~]+)([\d.]+)", vr)
    if not parts:
        return None

    for op, ver_s in parts:
        v = _parse_version(ver_s)
        if v is None:
            continue
        if op in (">=", "=>") and tv < v:
            return False
        elif op == ">" and tv <= v:
            return False
        elif op in ("<=", "=<") and tv > v:
            return False
        elif op == "<" and tv >= v:
            return False
        elif op in ("=", "==") and tv != v:
            return False
        elif op == "^" and tv[0] != v[0]:
            return False
        elif op == "~" and tv[:2] != v[:2]:
            return False

    return True


def _parse_version(s: str) -> Optional[tuple]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return None


def _compare_versions(a: str, b: str) -> int:
    av = _parse_version(a)
    bv = _parse_version(b)
    if av is None or bv is None:
        return 0
    if av > bv:
        return 1
    if av < bv:
        return -1
    return 0
