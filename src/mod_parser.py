import zipfile
import json
import os
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ModDependency:
    mod_id: str
    version_range: str
    mandatory: bool = True


@dataclass
class ModInfo:
    file_path: str
    file_name: str
    mod_id: str = ""
    name: str = ""
    version: str = ""
    loader: str = "unknown"
    mc_version_range: str = "*"
    dependencies: List[ModDependency] = field(default_factory=list)
    is_valid: bool = True
    error: str = ""
    description: str = ""
    authors: str = ""


def parse_jar(jar_path: str) -> ModInfo:
    file_name = os.path.basename(jar_path)
    info = ModInfo(file_path=jar_path, file_name=file_name)

    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            names = set(zf.namelist())

            if "fabric.mod.json" in names:
                return _parse_fabric(zf, info)

            if "quilt.mod.json" in names:
                return _parse_quilt(zf, info)

            if "META-INF/neoforge.mods.toml" in names:
                info.loader = "neoforge"
                with zf.open("META-INF/neoforge.mods.toml") as f:
                    _parse_forge_toml(f.read().decode("utf-8", errors="replace"), info)
                return info

            if "META-INF/mods.toml" in names:
                info.loader = "forge"
                with zf.open("META-INF/mods.toml") as f:
                    _parse_forge_toml(f.read().decode("utf-8", errors="replace"), info)
                return info

            info.loader = "unknown"
            info.name = file_name
            info.mod_id = re.sub(r"[-_][\d.]+.*$", "", file_name.replace(".jar", ""))
            info.error = "No mod manifest found (fabric.mod.json / mods.toml)"
            return info

    except zipfile.BadZipFile:
        info.is_valid = False
        info.name = file_name
        info.error = "Corrupted JAR file (not a valid ZIP archive)"
        return info
    except Exception as exc:
        info.is_valid = False
        info.name = file_name
        info.error = f"Parse error: {exc}"
        return info


def _parse_fabric(zf: zipfile.ZipFile, info: ModInfo) -> ModInfo:
    info.loader = "fabric"
    with zf.open("fabric.mod.json") as f:
        data = json.loads(f.read().decode("utf-8", errors="replace"))

    info.mod_id = data.get("id", "")
    info.name = data.get("name", info.file_name)
    info.version = data.get("version", "")
    info.description = data.get("description", "")

    authors = data.get("authors", [])
    if isinstance(authors, list):
        info.authors = ", ".join(
            a if isinstance(a, str) else a.get("name", "") for a in authors
        )

    depends = data.get("depends", {})
    info.mc_version_range = str(depends.get("minecraft", "*"))

    skip = {"minecraft", "fabricloader", "java"}
    for dep_id, dep_ver in depends.items():
        if dep_id not in skip:
            info.dependencies.append(
                ModDependency(dep_id, str(dep_ver) if not isinstance(dep_ver, str) else dep_ver)
            )
    return info


def _parse_quilt(zf: zipfile.ZipFile, info: ModInfo) -> ModInfo:
    info.loader = "quilt"
    with zf.open("quilt.mod.json") as f:
        data = json.loads(f.read().decode("utf-8", errors="replace"))

    ql = data.get("quilt_loader", {})
    info.mod_id = ql.get("id", "")
    info.name = ql.get("metadata", {}).get("name", info.file_name)
    info.version = ql.get("version", "")
    info.description = ql.get("metadata", {}).get("description", "")

    skip = {"quilt_loader", "java", "quilted_fabric_api"}
    for dep in ql.get("depends", []):
        if not isinstance(dep, dict):
            continue
        dep_id = dep.get("id", "")
        dep_ver = str(dep.get("versions", "*"))
        if dep_id == "minecraft":
            info.mc_version_range = dep_ver
        elif dep_id not in skip:
            info.dependencies.append(ModDependency(dep_id, dep_ver))
    return info


def _parse_forge_toml(content: str, info: ModInfo) -> None:
    mods_block = re.search(r"\[\[mods\]\](.*?)(?=\[\[|\Z)", content, re.DOTALL)
    if mods_block:
        block = mods_block.group(1)
        m = re.search(r'modId\s*=\s*["\']([^"\']+)["\']', block)
        if m:
            info.mod_id = m.group(1)
        m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', block)
        if m:
            ver = m.group(1)
            info.version = "" if ver.startswith("${") else ver
        m = re.search(r'displayName\s*=\s*["\']([^"\']+)["\']', block)
        info.name = m.group(1) if m else (info.mod_id or info.file_name)
        m = re.search(r'description\s*=\s*"""(.*?)"""', block, re.DOTALL)
        if not m:
            m = re.search(r'description\s*=\s*["\']([^"\']+)["\']', block)
        if m:
            info.description = m.group(1).strip()[:200]
    else:
        info.name = info.file_name

    skip = {"forge", "neoforge", "java", "fml"}
    for dep_block in re.finditer(
        r"\[\[dependencies\.[^\]]+\]\](.*?)(?=\[\[|\Z)", content, re.DOTALL
    ):
        bc = dep_block.group(1)
        id_m = re.search(r'modId\s*=\s*["\']([^"\']+)["\']', bc)
        ver_m = re.search(r'versionRange\s*=\s*["\']([^"\']+)["\']', bc)
        mand_m = re.search(r'mandatory\s*=\s*(true|false)', bc)
        if not id_m:
            continue
        dep_id = id_m.group(1)
        dep_ver = ver_m.group(1) if ver_m else "*"
        mandatory = mand_m.group(1) != "false" if mand_m else True
        if dep_id == "minecraft":
            info.mc_version_range = dep_ver
        elif dep_id not in skip:
            info.dependencies.append(ModDependency(dep_id, dep_ver, mandatory))


def scan_folder(folder_path: str) -> List[ModInfo]:
    results = []
    try:
        for fname in os.listdir(folder_path):
            if fname.lower().endswith(".jar") and not fname.lower().endswith(".jar.disabled"):
                results.append(parse_jar(os.path.join(folder_path, fname)))
    except PermissionError:
        pass
    return results
