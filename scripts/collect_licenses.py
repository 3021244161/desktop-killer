"""Copy original installed dependency notices; never synthesize license terms."""
from __future__ import annotations

import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "packaging" / "licenses"
PACKAGES = ("pygame", "Pillow", "numpy", "pywin32", "PyInstaller",
            "typing_extensions", "psutil", "defusedxml")
NATIVE_GAPS = ("SDL2", "SDL2_image", "SDL2_mixer", "SDL2_ttf", "FreeType",
               "libjpeg", "libpng", "libtiff", "libwebp", "libogg", "libopus",
               "libopusfile", "libmodplug", "PortMidi", "pygame freesansbold.ttf")


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    records, local_sources, missing = [], [], []

    def copy(component: str, version: str, files: list[Path]) -> None:
        if not files:
            missing.append(component)
            return
        entries = []
        for index, source in enumerate(files):
            name = f"{index + 1:02d}-{source.name}"
            target = DESTINATION / component / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            entries.append({"file": str(target.relative_to(DESTINATION)).replace("\\", "/"),
                            "sha256": digest})
            local_sources.append({"component": component, "source": str(source),
                                  "destination": str(target), "sha256": digest})
        records.append({"component": component, "version": version, "notices": entries})

    copy("Python", sys.version.split()[0], [Path(sys.prefix) / "LICENSE_PYTHON.txt"])
    for name in PACKAGES:
        package = distribution(name)
        files = [Path(package.locate_file(f)) for f in package.files or []
                 if any(token in str(f).lower() for token in ("license", "copying", "notice"))]
        if name == "pygame":
            files.append(Path(package.locate_file("pygame/docs/generated/LGPL.txt")))
        copy(name, package.version, sorted({f for f in files if f.is_file()}))
    for name in ("openssl", "libffi", "bzip2", "xz", "zlib", "vc14_runtime", "ucrt"):
        for meta in (Path(sys.prefix) / "conda-meta").glob(name + "-*.json"):
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data["name"] != name:
                continue
            directory = Path(sys.prefix) / "pkgs" / meta.stem / "info" / "licenses"
            copy(name, data["version"], sorted(f for f in directory.rglob("*") if f.is_file()))
    native_inventory = DESTINATION / "native" / "binary-inventory.json"
    supplemented = native_inventory.is_file()
    manifest = {"components": records, "missing_primary_notices": missing,
                "native_notices_not_present_in_installed_pygame": NATIVE_GAPS,
                "upstream_native_notices_supplemented": supplemented}
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    notice = ["THIRD-PARTY NOTICES", "", "Original installed license and notice files are preserved in this directory.",
              "This inventory is not a new license and does not replace any original terms.",
              "", "Collected components:"]
    notice += [f"- {record['component']} {record['version']}: {record['component']}/" for record in records]
    if supplemented:
        notice += ["", "Native libraries:",
                   "Additional original upstream notices are preserved in native/.",
                   "native/sources.json records exact source URLs and notice SHA256 checksums.",
                   "native/binary-inventory.json records the installed DLL hashes and version evidence.",
                   "SDL, SDL_image, SDL_mixer, SDL_ttf, FreeType, JPEG, PNG, TIFF, WebP, Opus and zlib",
                   "versions were verified from the installed binaries or their version APIs.",
                   "Ogg, Opusfile and ModPlug notices were taken from SDL_mixer 2.6.2's pinned official",
                   "submodules; their exact installed DLL revision was not independently established.",
                   "PortMidi's original official license is included; its exact DLL revision remains unverified.",
                   "FreeSans-notice.txt preserves the actual shipped font's copyright and license metadata.",
                   "This inventory does not claim that the pygame LGPL covers all native libraries.",
                   "", "Required acknowledgements:",
                   "Portions of this software are copyright (C) 2021 The FreeType Project",
                   "(https://www.freetype.org). All rights reserved.",
                   "This software is based in part on the work of the Independent JPEG Group.",
                   "", "Library source locations:",
                   "pygame 2.6.1: https://github.com/pygame/pygame/tree/2.6.1",
                   "pygame Windows dependency manifest: https://github.com/pygame/pygame/blob/2.6.1/buildconfig/download_win_prebuilt.py",
                   "Other corresponding upstream versions and files: native/sources.json.",
                   "Bundled libraries have not been modified by this project."]
    else:
        notice += ["", "Known inventory gap:",
                   "Original native notices were not installed alongside pygame and have not yet been supplemented:",
                   ", ".join(NATIVE_GAPS)]
    notice += ["", "See manifest.json for exact copied-file SHA256 checksums."]
    (DESTINATION / "NOTICE.txt").write_text("\n".join(notice) + "\n", encoding="utf-8")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "license-sources.json").write_text(json.dumps(local_sources, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"components": len(records), "original_files": len(local_sources),
                      "missing_primary_notices": missing, "upstream_native_notices_supplemented": supplemented,
                      "native_notice_gaps": [] if supplemented else NATIVE_GAPS}, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
