"""
Fonts for burned-in text.

Every on-screen word ClipsAI draws goes through this module: caption presets,
hook cards, thumbnails. It keeps one catalog of font faces (bundled Open Font
License files plus common system families) and resolves a name to both a file
(Pillow) and a family name (libass), so a preview and a burn cannot drift apart.

Bundled faces live in ``clipsai/fonts`` and ship with the package. Licences sit
next to them.

Example
-------
>>> from clipsai.typography import available_fonts, load_font, resolve_font
>>> [face["key"] for face in available_fonts()][:3]
['montserrat-extrabold', 'archivo-black', 'noto-serif']
>>> load_font(96, "montserrat-extrabold").getlength("HOOK") > 0
True
"""

# standard library imports
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 3rd party imports
from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

DEFAULT_FONT = "montserrat-extrabold"

#: Families that are already installed on the host (or aliased by fontconfig in
#: the Docker image) and must not be resolved to a bundled file.
SYSTEM_FAMILIES = (
    "Arial",
    "Arial Black",
    "Helvetica",
    "Georgia",
    "Verdana",
    "Impact",
    "Trebuchet MS",
    "DejaVu Sans",
    "Liberation Sans",
    "Liberation Serif",
)

#: Where a family falls back when the requested one is missing from the image.
_SYSTEM_FILES = {
    "Arial": (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
    "Arial Black": (
        "C:/Windows/Fonts/ariblk.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    ),
    "Impact": (
        "C:/Windows/Fonts/impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
    ),
    "Georgia": (
        "C:/Windows/Fonts/georgiab.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    ),
    "Verdana": (
        "C:/Windows/Fonts/verdanab.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
}


class FontError(Exception):
    """Raised when a requested font cannot be resolved."""


@dataclass(frozen=True)
class FontFace:
    """One selectable typeface."""

    key: str
    label: str
    family: str
    file: str = ""
    weight: int = 700
    variable: bool = False
    role: str = "display"
    source: str = ""

    @property
    def bundled(self) -> bool:
        return bool(self.file) and (FONT_DIR / self.file).is_file()

    def path(self) -> str:
        """Absolute path of the face's file (bundled or system fallback)."""
        if self.file and (FONT_DIR / self.file).is_file():
            return str(FONT_DIR / self.file)
        for candidate in _SYSTEM_FILES.get(self.family, ()):
            if os.path.isfile(candidate):
                return candidate
        return ""


FONT_CATALOG = {
    "montserrat-extrabold": FontFace(
        key="montserrat-extrabold",
        label="Montserrat ExtraBold",
        family="Montserrat ExtraBold",
        file="Montserrat-ExtraBold.ttf",
        role="display",
        source="https://fonts.google.com/specimen/Montserrat",
    ),
    "archivo-black": FontFace(
        key="archivo-black",
        label="Archivo Black",
        family="Archivo Black",
        file="ArchivoBlack-Regular.ttf",
        role="display",
        source="https://fonts.google.com/specimen/Archivo+Black",
    ),
    "noto-serif": FontFace(
        key="noto-serif",
        label="Noto Serif Bold",
        family="Noto Serif",
        file="NotoSerif-Bold.ttf",
        role="text",
        source="https://fonts.google.com/noto/specimen/Noto+Serif",
    ),
    "arial": FontFace(
        key="arial",
        label="Arial Bold (system)",
        family="Arial",
        role="system",
    ),
    "arial-black": FontFace(
        key="arial-black",
        label="Arial Black (system)",
        family="Arial Black",
        role="system",
    ),
    "impact": FontFace(
        key="impact",
        label="Impact (system)",
        family="Impact",
        role="system",
    ),
    "georgia": FontFace(
        key="georgia",
        label="Georgia Bold (system)",
        family="Georgia",
        role="system",
    ),
}

#: Order shown in menus: bundled faces first, then system fallbacks.
FONT_ORDER = (
    "montserrat-extrabold",
    "archivo-black",
    "noto-serif",
    "arial-black",
    "impact",
    "arial",
    "georgia",
)

_ALIASES = {
    "montserrat": "montserrat-extrabold",
    "montserrat-extra-bold": "montserrat-extrabold",
    "montserrat extra bold": "montserrat-extrabold",
    "montserrat extrabold": "montserrat-extrabold",
    "archivo": "archivo-black",
    "archivo black": "archivo-black",
    "noto": "noto-serif",
    "notoserif": "noto-serif",
    "note serif": "noto-serif",
    "noto serif bold": "noto-serif",
    "arial bold": "arial",
    "helvetica": "arial",
    "verdana": "arial",
    "georgia bold": "georgia",
}


def available_fonts(include_system: bool = True) -> "list[dict]":
    """Catalog entries for menus, in display order."""
    faces = []
    for key in FONT_ORDER:
        face = FONT_CATALOG[key]
        if face.bundled or (include_system and face.role == "system"):
            faces.append(
                {
                    "key": face.key,
                    "label": face.label,
                    "family": face.family,
                    "bundled": face.bundled,
                    "role": face.role,
                    "source": face.source,
                }
            )
    return faces


def font_keys() -> "tuple[str, ...]":
    return tuple(face["key"] for face in available_fonts())


def normalize_font(name: "str | None") -> str:
    """Canonical catalog key for ``name``, or ``""`` when it is not one of ours.

    Accepts a key, a family name, a file name or a path. Callers that already
    hold a raw libass family name (from an old preset) get ``""`` back and keep
    using that name unchanged.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    for key, face in FONT_CATALOG.items():
        if lowered in (key.lower(), face.family.lower(), face.label.lower()):
            return key
        if face.file and lowered == face.file.lower():
            return key
    stem = Path(raw).stem.lower()
    for key, face in FONT_CATALOG.items():
        if face.file and stem == Path(face.file).stem.lower():
            return key
    return ""


def get_face(name: "str | None") -> FontFace:
    """The catalog face for ``name`` (falls back to the default face)."""
    key = normalize_font(name) or DEFAULT_FONT
    return FONT_CATALOG[key]


def font_family(name: "str | None") -> str:
    """libass family name for ``name``.

    Catalog keys resolve to the family registered by their font file. Anything
    unrecognised is passed through: presets are allowed to name a family that is
    installed on the host.
    """
    key = normalize_font(name)
    if key:
        return FONT_CATALOG[key].family
    raw = str(name or "").strip()
    return raw or FONT_CATALOG[DEFAULT_FONT].family


def resolve_font(name: "str | None") -> str:
    """Path of a font file for \`\`name\`\`.

    ``name`` may be a catalog key, a family name, a path to a font file, or a
    file name inside :data:`FONT_DIR`. Raises :class:`FontError` when nothing
    usable is found. An empty ``name`` resolves to the default bundled face.
    """
    raw = str(name or "").strip()
    if raw:
        candidate = Path(raw)
        if candidate.is_file() and candidate.suffix.lower() in (".ttf", ".otf", ".ttc"):
            return str(candidate)
        inside = FONT_DIR / raw
        if inside.is_file():
            return str(inside)
        key = normalize_font(raw)
        if key:
            path = FONT_CATALOG[key].path()
            if path:
                return path
        # A bare family name ("Helvetica Neue") may still be installed on the
        # host; do not silently substitute the branded default for it. Callers
        # that need libass only (no Pillow file) use ``font_family`` instead.
        raise FontError(
            "Could not resolve font '{}'. Bundled fonts: {}. System families: {}.".format(
                raw,
                ", ".join(font_keys()),
                ", ".join(SYSTEM_FAMILIES),
            )
        )

    face = FONT_CATALOG[DEFAULT_FONT]
    path = face.path()
    if path:
        return path
    raise FontError("The default font '{}' is missing.".format(DEFAULT_FONT))


def fonts_dir() -> str:
    """Folder libass should search for the bundled faces."""
    return str(FONT_DIR)


def load_font(
    size: int, name: "str | None" = None, weight: "int | None" = None
) -> "ImageFont.FreeTypeFont":
    """Load a Pillow font at ``size`` px, honouring a variable weight axis."""
    face = get_face(name)
    path = resolve_font(name)
    try:
        font = ImageFont.truetype(path, int(size))
    except OSError as exc:  # pragma: no cover - depends on the host
        raise FontError("Could not open font file '{}': {}".format(path, exc)) from exc
    if face.variable or weight is not None:
        try:
            font.set_variation_by_axes([int(weight or face.weight)])
        except Exception:  # noqa: BLE001 - static fonts reject the axis
            pass
    return font


def font_summary() -> "list[dict]":
    """Short, printable description of what is installed."""
    rows = []
    for face in available_fonts():
        rows.append(
            {
                "key": face["key"],
                "label": face["label"],
                "family": face["family"],
                "file": FONT_CATALOG[face["key"]].path() or "(libass/system)",
            }
        )
    return rows
