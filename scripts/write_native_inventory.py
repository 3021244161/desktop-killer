"""Record which original upstream notice was matched to each installed binary."""
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "packaging" / "licenses" / "native"
# Versions were read from this installed wheel's DLL resources, version APIs or
# embedded version strings. A source manifest is not evidence of a binary hash.
MATCHES = {
    "SDL2.dll": ("2.28.4", "DLL resource and SDL version API", "SDL2-LICENSE.txt"),
    "SDL2_image.dll": ("2.0.5", "DLL resource and SDL_image version API", "SDL2_image-LICENSE.txt"),
    "SDL2_mixer.dll": ("2.6.2", "DLL resource and SDL_mixer version API", "SDL2_mixer-LICENSE.txt"),
    "SDL2_ttf.dll": ("2.20.1", "DLL resource and SDL_ttf version API", "SDL2_ttf-LICENSE.txt"),
    "freetype.dll": ("2.11.1", "DLL resource and FreeType version API", "FreeType-FTL.txt"),
    "libjpeg-9.dll": ("9b", "Embedded 9b 17-Jan-2016 string", "libjpeg-README.txt"),
    "libpng16-16.dll": ("1.6.37", "Embedded libpng version string", "libpng-LICENSE.txt"),
    "libtiff-5.dll": ("4.0.9", "Embedded LIBTIFF Version 4.0.9 string", "libtiff-COPYRIGHT.txt"),
    "libwebp-7.dll": ("1.0.2", "WebPGetDecoderVersion API", "libwebp-COPYING.txt"),
    "libopus-0.dll": ("1.3.1", "Embedded libopus 1.3.1 string", "libopus-COPYING.txt"),
    "zlib1.dll": ("1.2.11", "DLL version resource", "zlib1-LICENSE.txt"),
    "libogg-0.dll": (None, "Notice from the SDL_mixer 2.6.2 pinned official submodule; exact DLL revision not independently established", "libogg-COPYING.txt"),
    "libopusfile-0.dll": (None, "Notice from the SDL_mixer 2.6.2 pinned official submodule; exact DLL revision not independently established", "libopusfile-COPYING.txt"),
    "libmodplug-1.dll": (None, "Notice and README from the SDL_mixer 2.6.2 pinned official submodule; exact DLL revision not independently established", "libmodplug-COPYING.txt"),
    "portmidi.dll": (None, "Original official PortMidi license; installed DLL has no exposed version and exact revision is not established", "PortMidi-license.txt"),
}


def main():
    directory = Path(pygame.__file__).parent
    rows = []
    for filename, (version, evidence, notice) in MATCHES.items():
        binary = directory / filename
        if not binary.is_file() or not (DESTINATION / notice).is_file():
            raise FileNotFoundError(filename + " or its original notice is missing")
        rows.append({"binary": filename, "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                     "version": version, "evidence": evidence, "primary_notice": notice})
    font_path = directory / "freesansbold.ttf"
    font = TTFont(font_path)
    metadata = {str(key): sorted({record.toUnicode() for record in font["name"].names if record.nameID == key})
                for key in (0, 1, 5, 13, 14)}
    font_notice = ["Original metadata from pygame 2.6.1 / freesansbold.ttf", "",
                   "Font SHA256: " + hashlib.sha256(font_path.read_bytes()).hexdigest(),
                   "Official pygame source: https://github.com/pygame/pygame/tree/2.6.1", ""]
    for label, key in (("Copyright", "0"), ("Family", "1"), ("Revision", "5"),
                       ("Original license description", "13"), ("Original license URL", "14")):
        font_notice += [label + ":", *metadata[key], ""]
    font_notice += ["The embedded metadata refers to the GNU GPL without naming a version.",
                    "A complete original GPL version 2 text is included as FreeSans-GPL-2.0.txt.",
                    "No new font license or embedding exception is claimed by this inventory."]
    (DESTINATION / "FreeSans-notice.txt").write_text("\n".join(font_notice) + "\n", encoding="utf-8")
    report = {"pygame": pygame.version.ver,
              "official_windows_dependency_manifest": "https://github.com/pygame/pygame/blob/2.6.1/buildconfig/download_win_prebuilt.py",
              "binaries": rows, "font_metadata": metadata}
    (DESTINATION / "binary-inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"binaries": len(rows), "version_verified": sum(row["version"] is not None for row in rows),
                      "unverified_exact_revision": [row["binary"] for row in rows if row["version"] is None]}))


if __name__ == "__main__":
    main()
