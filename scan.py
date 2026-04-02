#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

EXPECTED_ARCWRT_URL = "ssh://gitolite@sw6-builder.arcadyan.com.tw/aldk-openwrt18/arcwrt.git"
LAST_UPDATE_CHOICES = ["1d", "3d", "1w", "2w", "4w", "8w", "12w", "24w", "52w", "64w", "76w"]


@dataclass(frozen=True)
class ProjectKey:
    pid: str
    ver: str

    def name(self) -> str:
        return f"{self.pid}/{self.ver}"

    def patch_dir_display(self) -> str:
        return f"./{self.pid}/{self.ver}/project_patch"

    def project_dir_display(self) -> str:
        return f"./{self.pid}/{self.ver}"

    def project_relpath(self) -> str:
        return f"project/{self.pid}/{self.ver}"


@dataclass
class RepoInfo:
    url: str = ""
    branch: str = ""
    commitid: str = ""


@dataclass(frozen=True)
class LastUpdateInfo:
    epoch: int
    commit_count: int


def parse_gits_info(path: Path) -> Tuple[Dict[str, RepoInfo], Dict[str, str]]:
    repos: Dict[str, RepoInfo] = {}
    kv: Dict[str, str] = {}
    if not path.exists():
        return repos, kv

    sec_re = re.compile(r"^\s*\[(.+?)\]\s*$")
    kv_re = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")

    cur = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = sec_re.match(line)
        if m:
            cur = m.group(1).strip()
            repos.setdefault(cur, RepoInfo())
            continue

        m = kv_re.match(raw)
        if not m:
            continue

        k = m.group(1).strip()
        v = m.group(2).strip().strip('"').strip("'")

        if cur:
            ri = repos.setdefault(cur, RepoInfo())
            if k.upper() == "URL":
                ri.url = v
            elif k.upper() == "BRANCH":
                ri.branch = v
            elif k.upper() == "COMMITID":
                ri.commitid = v
            else:
                kv[k] = v
        else:
            kv[k] = v

    return repos, kv


def parse_dot_config(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    kv_re = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = kv_re.match(raw)
        if not m:
            continue
        k = m.group(1).strip()
        v = m.group(2).strip().strip('"').strip("'")
        out[k] = v
    return out


def get_repo_case_insensitive(repos: Dict[str, RepoInfo], name: str) -> RepoInfo:
    for k, v in repos.items():
        if k.lower() == name.lower():
            return v
    return RepoInfo()


def branch_to_openwrt_version(branch: str) -> str:
    branch = (branch or "").strip()
    if not branch:
        return "unknown"
    if re.fullmatch(r"[0-9.]+", branch):
        return branch[:5]
    return branch


def project_is_allowed(ver_dir: Path) -> bool:
    gits_conf = ver_dir / ".gits_conf"
    if not gits_conf.exists():
        return True

    repos, _ = parse_gits_info(gits_conf)
    arcwrt = get_repo_case_insensitive(repos, "arcwrt")

    if arcwrt.url != EXPECTED_ARCWRT_URL:
        return False
    if arcwrt.branch != "master":
        return False
    if (arcwrt.commitid or "").strip():
        return False
    return True


def parse_project_openwrt_version(ver_dir: Path) -> str:
    gits_conf = ver_dir / ".gits_conf"
    if gits_conf.exists():
        repos, _ = parse_gits_info(gits_conf)
        ow = get_repo_case_insensitive(repos, "openwrt")
        return branch_to_openwrt_version(ow.branch)

    cfg = parse_dot_config(ver_dir / ".config")
    return branch_to_openwrt_version(cfg.get("CONFIG_OPENWRT_GIT_BRANCH", ""))


def parse_project_bsp(ver_dir: Path) -> str:
    cfg = parse_dot_config(ver_dir / ".config")
    return (cfg.get("CONFIG_BSP_FOLDER_NAME") or "").strip() or "unknown-bsp"


def scan_tree_provides(root: Path) -> Set[str]:
    provides: Set[str] = set()
    if not root.exists():
        return provides

    for p in root.rglob("*"):
        try:
            if p.is_dir():
                continue
        except OSError:
            continue

        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in rel:
            continue
        if rel.endswith(".delete"):
            continue

        try:
            if p.is_file() or p.is_symlink():
                provides.add(rel)
        except OSError:
            continue

    return provides


def feed_rel_to_candidates(feed_rel: str) -> List[str]:
    cands = [feed_rel, f"feeds/feeds_addon/{feed_rel}"]
    if feed_rel.startswith("package/"):
        cands.append(f"package/feeds/feeds_addon/{feed_rel[len('package/'):]}")
    else:
        cands.append(f"package/feeds/feeds_addon/{feed_rel}")

    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def collect_projects(arcwrt_root: Path) -> Dict[ProjectKey, Tuple[str, str]]:
    proj_root = arcwrt_root / "project"
    out: Dict[ProjectKey, Tuple[str, str]] = {}
    if not proj_root.exists():
        return out

    for pid_dir in sorted([p for p in proj_root.iterdir() if p.is_dir() and p.name != ".git"]):
        pid = pid_dir.name
        for ver_dir in sorted([p for p in pid_dir.iterdir() if p.is_dir() and p.name != ".git"]):
            pk = ProjectKey(pid, ver_dir.name)

            if not project_is_allowed(ver_dir):
                continue

            bspv = parse_project_bsp(ver_dir)
            ov = parse_project_openwrt_version(ver_dir)
            out[pk] = (ov, bspv)

    return out


def scan_all_generic_patches(arcwrt_root: Path) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, str], Set[str]]]:
    base = arcwrt_root / "openwrt_patch" / "generic_patch"
    gpo_by_ov: Dict[str, Set[str]] = {}
    gpob_by_combo: Dict[Tuple[str, str], Set[str]] = {}

    if not base.exists():
        return gpo_by_ov, gpob_by_combo

    for ov_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
        ov = ov_dir.name

        oc = ov_dir / "openwrt_common"
        if oc.exists() and oc.is_dir():
            gpo_by_ov[ov] = scan_tree_provides(oc)

        for bsp_dir in sorted([p for p in ov_dir.iterdir() if p.is_dir()]):
            if bsp_dir.name == "openwrt_common":
                continue
            bspv = bsp_dir.name
            gpob_by_combo[(ov, bspv)] = scan_tree_provides(bsp_dir)

    return gpo_by_ov, gpob_by_combo


def build_existing_gpob_users(
    projects: Dict[ProjectKey, Tuple[str, str]],
    gpob_by_combo: Dict[Tuple[str, str], Set[str]],
) -> Dict[Tuple[str, str], List[ProjectKey]]:
    combo_to_projects: Dict[Tuple[str, str], List[ProjectKey]] = {combo: [] for combo in gpob_by_combo.keys()}
    for pk, (ov, bspv) in projects.items():
        if ov == "unknown" or bspv == "unknown-bsp":
            continue
        combo = (ov, bspv)
        if combo in gpob_by_combo:
            combo_to_projects[combo].append(pk)
    for combo in combo_to_projects:
        combo_to_projects[combo].sort(key=lambda p: (p.pid, p.ver))
    return combo_to_projects


def scan_project_patches(arcwrt_root: Path, projects: Dict[ProjectKey, Tuple[str, str]]) -> Dict[ProjectKey, Set[str]]:
    out: Dict[ProjectKey, Set[str]] = {}
    for pk in projects.keys():
        root = arcwrt_root / "project" / pk.pid / pk.ver / "project_patch"
        out[pk] = scan_tree_provides(root)
    return out


def parse_age_spec(spec: str) -> int:
    m = re.fullmatch(r"(\d+)([dw])", spec)
    if not m:
        raise ValueError(f"invalid age spec: {spec}")
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return n * 86400
    return n * 7 * 86400


def git_last_update_epoch(arcwrt_root: Path, pk: ProjectKey) -> Optional[int]:
    candidates = [
        pk.project_relpath(),
        f"{pk.project_relpath()}/project_patch",
        f"{pk.project_relpath()}/.config",
        f"{pk.project_relpath()}/.gits_conf",
        f"{pk.project_relpath()}/.gits_info",
    ]

    for rel in candidates:
        try:
            proc = subprocess.run(
                ["git", "-C", str(arcwrt_root / "project"), "log", "-1", "--format=%ct", "--", rel.removeprefix("project/")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError:
            return None

        if proc.returncode != 0:
            continue

        out = proc.stdout.strip()
        if out and out.isdigit():
            return int(out)

    return None




def git_commit_count(arcwrt_root: Path, pk: ProjectKey) -> int:
    try:
        proc = subprocess.run(
            ["git", "-C", str(arcwrt_root / "project"), "rev-list", "--count", "HEAD", "--", f"{pk.pid}/{pk.ver}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return 0

    out = proc.stdout.strip()
    return int(out) if proc.returncode == 0 and out.isdigit() else 0

def format_age(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days = seconds // 86400
    return f"{days}d"



def gen_last_update_all(arcwrt_root: Path, projects: Dict[ProjectKey, Tuple[str, str]]) -> List[Tuple[str, List[str]]]:
    now = int(time.time())
    matched: List[Tuple[int, int, ProjectKey, str, str]] = []

    for pk, (ov, bspv) in projects.items():
        epoch = git_last_update_epoch(arcwrt_root, pk)
        if epoch is None:
            continue
        commit_count = git_commit_count(arcwrt_root, pk)
        matched.append((epoch, commit_count, pk, ov, bspv))

    matched.sort(key=lambda x: (-x[0], x[2].pid, x[2].ver))

    items: List[Tuple[str, List[str]]] = []
    for epoch, commit_count, pk, ov, bspv in matched:
        age = max(0, now - epoch)
        title = f"{commit_count}  {pk.project_dir_display()}"
        lines = [
            f"	last_update_epoch = {epoch}",
            f"	age = {format_age(age)}",
            f"	openwrt version = {ov}",
            f"	bsp version = {bspv}",
        ]
        items.append((title, lines))
    return items


def gen_last_update_in(arcwrt_root: Path, projects: Dict[ProjectKey, Tuple[str, str]], spec: str) -> List[Tuple[str, List[str]]]:
    threshold = parse_age_spec(spec)
    now = int(time.time())
    matched: List[Tuple[int, int, ProjectKey, str, str]] = []

    for pk, (ov, bspv) in projects.items():
        epoch = git_last_update_epoch(arcwrt_root, pk)
        if epoch is None:
            continue
        age = now - epoch
        if age <= threshold:
            commit_count = git_commit_count(arcwrt_root, pk)
            matched.append((epoch, commit_count, pk, ov, bspv))

    matched.sort(key=lambda x: (-x[0], x[2].pid, x[2].ver))

    items: List[Tuple[str, List[str]]] = []
    for epoch, commit_count, pk, ov, bspv in matched:
        age = max(0, now - epoch)
        title = f"{commit_count}  {pk.project_dir_display()}"
        lines = [
            f"	last_update_epoch = {epoch}",
            f"	age = {format_age(age)}",
            f"	openwrt version = {ov}",
            f"	bsp version = {bspv}",
        ]
        items.append((title, lines))
    return items


def gen_no_update_in(arcwrt_root: Path, projects: Dict[ProjectKey, Tuple[str, str]], days: int) -> List[str]:
    threshold = days * 86400
    now = int(time.time())
    matched: List[Tuple[int, ProjectKey]] = []

    for pk in projects.keys():
        epoch = git_last_update_epoch(arcwrt_root, pk)
        if epoch is None:
            continue
        age = now - epoch
        if age > threshold:
            matched.append((epoch, pk))

    matched.sort(key=lambda x: (x[0], x[1].pid, x[1].ver))
    return [f"project/{pk.name()}" for _, pk in matched]


def gen_conflict_fa(

    arcwrt_root: Path,
    projects: Dict[ProjectKey, Tuple[str, str]],
    project_provides: Dict[ProjectKey, Set[str]],
) -> List[Tuple[str, List[str]]]:
    feeds_root = arcwrt_root / "feeds_addon"
    feed_files = scan_tree_provides(feeds_root)
    items: List[Tuple[str, List[str]]] = []

    for feed_rel in sorted(feed_files):
        feed_src = feeds_root / feed_rel
        if not (feed_src.is_file() or feed_src.is_symlink()):
            continue

        candidates = feed_rel_to_candidates(feed_rel)

        flat_projects: Set[str] = set()
        for pk in projects.keys():
            if any(c in project_provides.get(pk, set()) for c in candidates):
                flat_projects.add(pk.patch_dir_display())

        if not flat_projects:
            continue

        lines = [f"\t{p}" for p in sorted(flat_projects)]
        items.append((f"feeds_addon/{feed_rel}", lines))

    return items


def gen_conflict_gpo(
    gpo_by_ov: Dict[str, Set[str]],
    gpob_by_combo: Dict[Tuple[str, str], Set[str]],
    gpob_users: Dict[Tuple[str, str], List[ProjectKey]],
    project_provides: Dict[ProjectKey, Set[str]],
) -> List[Tuple[str, List[str]]]:
    gpob_combos_by_ov: Dict[str, List[Tuple[str, str]]] = {}
    for (ov, bspv) in gpob_by_combo.keys():
        gpob_combos_by_ov.setdefault(ov, []).append((ov, bspv))
    for ov in gpob_combos_by_ov.keys():
        gpob_combos_by_ov[ov].sort(key=lambda x: x[1])

    items: List[Tuple[str, List[str]]] = []

    for ov in sorted(gpo_by_ov.keys()):
        combos = gpob_combos_by_ov.get(ov, [])
        if not combos:
            continue

        for rel in sorted(gpo_by_ov[ov]):
            providers: List[Tuple[Tuple[str, str], List[str]]] = []
            for (ov2, bspv) in combos:
                if rel not in gpob_by_combo.get((ov2, bspv), set()):
                    continue
                proj_list = []
                for pk in gpob_users.get((ov2, bspv), []):
                    if rel in project_provides.get(pk, set()):
                        proj_list.append(pk.patch_dir_display())
                providers.append(((ov2, bspv), sorted(set(proj_list))))

            if not providers:
                continue

            lines: List[str] = []
            for (ov2, bspv), proj_list in providers:
                lines.append(f"\t\tgeneric_patch/{ov2}/{bspv}")
                for p in proj_list:
                    lines.append(f"\t\t\t{p}")

            title = f"generic_patch/{ov}/openwrt_common/{rel}"
            items.append((title, lines))

    return items


def gen_conflict_gpob(
    gpob_by_combo: Dict[Tuple[str, str], Set[str]],
    gpob_users: Dict[Tuple[str, str], List[ProjectKey]],
    project_provides: Dict[ProjectKey, Set[str]],
) -> List[Tuple[str, List[str]]]:
    items: List[Tuple[str, List[str]]] = []
    for (ov, bspv) in sorted(gpob_by_combo.keys()):
        proj_list = gpob_users.get((ov, bspv), [])
        if not proj_list:
            continue

        for rel in sorted(gpob_by_combo[(ov, bspv)]):
            users = []
            for pk in proj_list:
                if rel in project_provides.get(pk, set()):
                    users.append(pk.patch_dir_display())
            if not users:
                continue
            title = f"generic_patch/{ov}/{bspv}/{rel}"
            lines = [f"\t{p}" for p in users]
            items.append((title, lines))
    return items


def gen_usage_count_gpob(
    arcwrt_root: Path,
    gpob_users: Dict[Tuple[str, str], List[ProjectKey]],
    include_last_update: bool = False,
) -> List[Tuple[str, List[str]]]:
    sortable: List[Tuple[int, str, str, List[ProjectKey]]] = []
    for (ov, bspv), proj_list in gpob_users.items():
        sortable.append((len(proj_list), ov, bspv, proj_list))

    sortable.sort(key=lambda x: (-x[0], x[1], x[2]))

    now = int(time.time())
    items: List[Tuple[str, List[str]]] = []
    for count, ov, bspv, proj_list in sortable:
        title = f"{count}   generic_patch/{ov}/{bspv}"
        detailed = []
        for pk in proj_list:
            epoch = git_last_update_epoch(arcwrt_root, pk)
            sort_epoch = epoch if epoch is not None else -1
            if include_last_update:
                age_s = "?" if epoch is None else format_age(max(0, now - epoch))
                line = f"            {age_s:>4} ./{pk.pid}/{pk.ver}"
            else:
                line = f"            ./{pk.pid}/{pk.ver}"
            detailed.append((sort_epoch, line))
        detailed.sort(key=lambda x: (-x[0], x[1]))
        lines = [line for _, line in detailed]
        items.append((title, lines))
    return items


def gen_usage_count_unknown_project(
    arcwrt_root: Path,
    projects: Dict[ProjectKey, Tuple[str, str]],
    gpob_by_combo: Dict[Tuple[str, str], Set[str]],
) -> List[Tuple[str, List[str]]]:
    existing = set(gpob_by_combo.keys())
    now = int(time.time())
    matched: List[Tuple[int, ProjectKey, List[str]]] = []
    unmatched_time: List[Tuple[ProjectKey, List[str]]] = []

    for pk, (ov, bspv) in projects.items():
        reasons: List[str] = []
        if ov == "unknown":
            reasons.append("cannot parse openwrt version from .gits_conf [openwrt] BRANCH or .config CONFIG_OPENWRT_GIT_BRANCH")
        if bspv == "unknown-bsp":
            reasons.append("cannot parse bsp version from .config CONFIG_BSP_FOLDER_NAME")
        if ov != "unknown" and bspv != "unknown-bsp" and (ov, bspv) not in existing:
            reasons.append(f"no matching directory: generic_patch/{ov}/{bspv}")

        if not reasons:
            continue

        epoch = git_last_update_epoch(arcwrt_root, pk)
        lines = [
            f"\tparsed openwrt version = {ov}",
            f"\tparsed bsp version = {bspv}",
        ] + [f"\t{r}" for r in reasons]

        if epoch is None:
            unmatched_time.append((pk, lines))
        else:
            matched.append((epoch, pk, lines))

    matched.sort(key=lambda x: (-x[0], x[1].pid, x[1].ver))
    unmatched_time.sort(key=lambda x: (x[0].pid, x[0].ver))

    items: List[Tuple[str, List[str]]] = []
    for _, pk, lines in matched:
        items.append((pk.patch_dir_display(), lines))
    for pk, lines in unmatched_time:
        items.append((pk.patch_dir_display(), lines))
    return items


def write_numbered_items(out_path: Path, items: List[Tuple[str, List[str]]], header_suffix: str = "") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for idx, (title, lines) in enumerate(items, start=1):
            if header_suffix:
                f.write(f"{idx}. {title} {header_suffix}\n")
            else:
                f.write(f"{idx}. {title}\n")
            for ln in lines:
                f.write(ln + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="ARCWrt monitor: conflict.fa / conflict.gpo / conflict.gpob")
    ap.add_argument("--arcwrt-root", default=".", help="path to arcwrt root")
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--conflict", choices=["fa", "gpo", "gpob"], help="generate only one conflict report")
    ap.add_argument("--usage-count", "--usage_count", dest="usage_count", choices=["gpob", "gpob_last_update", "unknown_project"], help="list usage_count report")
    ap.add_argument("--last-update-in", choices=LAST_UPDATE_CHOICES, help="list projects updated within a recent time window")
    ap.add_argument("--last-update", action="store_true", help="list all projects and their last update time")
    ap.add_argument("--no-update-in", metavar="<x>d", help="print projects with no update in the last x days, for example 7d")
    args = ap.parse_args()

    arcwrt_root = Path(args.arcwrt_root).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    projects = collect_projects(arcwrt_root)
    if not projects:
        raise SystemExit(f"[ERR] No projects found under {arcwrt_root}/project/*/*")

    gpo_by_ov, gpob_by_combo = scan_all_generic_patches(arcwrt_root)
    gpob_users = build_existing_gpob_users(projects, gpob_by_combo)

    if args.no_update_in:
        m = re.fullmatch(r"([1-9][0-9]*)d", args.no_update_in)
        if not m:
            raise SystemExit("[ERR] --no-update-in must be like 7d, where x is a positive integer")
        items = gen_no_update_in(arcwrt_root, projects, int(m.group(1)))
        for s in items:
            print(s)
        return 0

    if args.last_update:
        items = gen_last_update_all(arcwrt_root, projects)
        out_path = out_dir / "last_update"
        write_numbered_items(out_path, items)
        print(f"[OK] wrote {out_path} items={len(items)}")
        return 0

    if args.last_update_in:
        items = gen_last_update_in(arcwrt_root, projects, args.last_update_in)
        out_path = out_dir / f"last_update_in.{args.last_update_in}"
        write_numbered_items(out_path, items)
        print(f"[OK] wrote {out_path} items={len(items)}")
        return 0

    if args.usage_count == "gpob":
        usage_items = gen_usage_count_gpob(arcwrt_root, gpob_users, include_last_update=False)
        write_numbered_items(out_dir / "usage_count.gpob", usage_items)
        print(f"[OK] wrote {out_dir/'usage_count.gpob'} items={len(usage_items)}")
        return 0

    if args.usage_count == "gpob_last_update":
        usage_items = gen_usage_count_gpob(arcwrt_root, gpob_users, include_last_update=True)
        write_numbered_items(out_dir / "usage_count.gpob_last_update", usage_items)
        print(f"[OK] wrote {out_dir/'usage_count.gpob_last_update'} items={len(usage_items)}")
        return 0

    if args.usage_count == "unknown_project":
        unknown_items = gen_usage_count_unknown_project(arcwrt_root, projects, gpob_by_combo)
        write_numbered_items(out_dir / "usage_count.unknown_project", unknown_items)
        print(f"[OK] wrote {out_dir/'usage_count.unknown_project'} items={len(unknown_items)}")
        return 0

    project_provides = scan_project_patches(arcwrt_root, projects)

    if args.conflict == "fa":
        fa_items = gen_conflict_fa(arcwrt_root, projects, project_provides)
        write_numbered_items(out_dir / "conflict.fa", fa_items, "is overridden by")
        print(f"[OK] wrote {out_dir/'conflict.fa'} items={len(fa_items)}")
        return 0

    if args.conflict == "gpo":
        gpo_items = gen_conflict_gpo(gpo_by_ov, gpob_by_combo, gpob_users, project_provides)
        write_numbered_items(out_dir / "conflict.gpo", gpo_items, "is overridden by")
        print(f"[OK] wrote {out_dir/'conflict.gpo'} items={len(gpo_items)}")
        return 0

    if args.conflict == "gpob":
        gpob_items = gen_conflict_gpob(gpob_by_combo, gpob_users, project_provides)
        write_numbered_items(out_dir / "conflict.gpob", gpob_items, "is overridden by")
        print(f"[OK] wrote {out_dir/'conflict.gpob'} items={len(gpob_items)}")
        return 0

    # default: generate the full report set
    fa_items = gen_conflict_fa(arcwrt_root, projects, project_provides)
    write_numbered_items(out_dir / "conflict.fa", fa_items, "is overridden by")
    print(f"[OK] wrote {out_dir/'conflict.fa'} items={len(fa_items)}")

    gpo_items = gen_conflict_gpo(gpo_by_ov, gpob_by_combo, gpob_users, project_provides)
    write_numbered_items(out_dir / "conflict.gpo", gpo_items, "is overridden by")
    print(f"[OK] wrote {out_dir/'conflict.gpo'} items={len(gpo_items)}")

    gpob_items = gen_conflict_gpob(gpob_by_combo, gpob_users, project_provides)
    write_numbered_items(out_dir / "conflict.gpob", gpob_items, "is overridden by")
    print(f"[OK] wrote {out_dir/'conflict.gpob'} items={len(gpob_items)}")

    usage_items = gen_usage_count_gpob(arcwrt_root, gpob_users)
    write_numbered_items(out_dir / "usage_count.gpob", usage_items)
    print(f"[OK] wrote {out_dir/'usage_count.gpob'} items={len(usage_items)}")

    unknown_items = gen_usage_count_unknown_project(arcwrt_root, projects, gpob_by_combo)
    write_numbered_items(out_dir / "usage_count.unknown_project", unknown_items)
    print(f"[OK] wrote {out_dir/'usage_count.unknown_project'} items={len(unknown_items)}")

    for spec in ("1w", "4w", "12w", "24w", "52w"):
        items = gen_last_update_in(arcwrt_root, projects, spec)
        out_path = out_dir / f"last_update_in.{spec}"
        write_numbered_items(out_path, items)
        print(f"[OK] wrote {out_path} items={len(items)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
