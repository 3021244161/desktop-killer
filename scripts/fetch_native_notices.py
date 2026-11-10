"""Fetch only original small license texts from pinned upstream sources."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import ssl
from pathlib import Path
from urllib.request import Request, urlopen

import certifi

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "SDL2-LICENSE.txt": "https://raw.githubusercontent.com/libsdl-org/SDL/release-2.28.4/LICENSE.txt",
    "SDL2_image-LICENSE.txt": "https://raw.githubusercontent.com/libsdl-org/SDL_image/release-2.0.5/COPYING.txt",
    "SDL2_mixer-LICENSE.txt": "https://raw.githubusercontent.com/libsdl-org/SDL_mixer/release-2.6.2/LICENSE.txt",
    "SDL2_ttf-LICENSE.txt": "https://raw.githubusercontent.com/libsdl-org/SDL_ttf/release-2.20.1/LICENSE.txt",
    "FreeType-FTL.txt": "https://raw.githubusercontent.com/freetype/freetype/VER-2-11-1/docs/FTL.TXT",
    "FreeType-LICENSE.txt": "https://raw.githubusercontent.com/freetype/freetype/VER-2-11-1/LICENSE.TXT",
    "libjpeg-README.txt": "https://raw.githubusercontent.com/libsdl-org/SDL_image/release-2.0.5/external/jpeg-9b/README",
    "libpng-LICENSE.txt": "https://raw.githubusercontent.com/pnggroup/libpng/v1.6.37/LICENSE",
    "libtiff-COPYRIGHT.txt": "https://raw.githubusercontent.com/libsdl-org/libtiff/v4.0.9/COPYRIGHT",
    "libwebp-COPYING.txt": "https://raw.githubusercontent.com/webmproject/libwebp/v1.0.2/COPYING",
    "libwebp-PATENTS.txt": "https://raw.githubusercontent.com/webmproject/libwebp/v1.0.2/PATENTS",
    "libwebp-AUTHORS.txt": "https://raw.githubusercontent.com/webmproject/libwebp/v1.0.2/AUTHORS",
    "libogg-COPYING.txt": "https://raw.githubusercontent.com/libsdl-org/ogg/790939cacc9a571bd2d3ca6c8fd49ddce5435399/COPYING",
    "libopus-COPYING.txt": "https://raw.githubusercontent.com/xiph/opus/v1.3.1/COPYING",
    "libopusfile-COPYING.txt": "https://raw.githubusercontent.com/libsdl-org/opusfile/b3f3d2c8977e506e0c673aee72b3901e4c3db8c7/COPYING",
    "libmodplug-COPYING.txt": "https://raw.githubusercontent.com/libsdl-org/libmodplug/ac378ae725e89195e6ffca6cfc68a64f16a1c650/COPYING",
    "libmodplug-README.txt": "https://raw.githubusercontent.com/libsdl-org/libmodplug/ac378ae725e89195e6ffca6cfc68a64f16a1c650/README",
    "PortMidi-license.txt": "https://raw.githubusercontent.com/PortMidi/portmidi/master/license.txt",
    "zlib1-LICENSE.txt": "https://raw.githubusercontent.com/madler/zlib/v1.2.11/README",
    "FreeSans-GPL-2.0.txt": "https://raw.githubusercontent.com/freetype/freetype/VER-2-11-1/docs/GPLv2.TXT",
}


def main():
    destination = ROOT / "packaging" / "licenses" / "native"
    destination.mkdir(parents=True, exist_ok=True)
    def fetch(item):
        filename, url = item
        try:
            # Use the installed CA bundle; never disable HTTPS verification.
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(Request(url, headers={"User-Agent": "DesktopKiller-license-inventory"}), timeout=25,
                         context=context) as response:
                data = response.read(200001)
            if not 10 <= len(data) <= 200000 or b"<!DOCTYPE" in data[:100].upper():
                raise ValueError("Expected a small original text notice")
            (destination / filename).write_bytes(data)
            return {"file": filename, "source": url, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}
        except Exception as error:
            return {"file": filename, "source": url, "error": str(error)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, SOURCES.items()))
    (destination / "sources.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return int(any("error" in result for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
