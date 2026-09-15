#!/usr/bin/env python3
"""Derive every launcher and splash asset from the two pieces of source art.

`assets/brand/` holds what the designer actually drew: the mountain mark, and
the mark with the TERRA RUN wordmark under it. Everything the app ships is a
mechanical transform of those two files, so it lives here as a script rather
than as a folder of binaries nobody can regenerate.

Three transforms are doing real work:

- **Recentring.** The mark's artwork sits 20 px right of centre in its own
  frame, which reads as a crooked icon once iOS rounds the corners. Every
  output is composed from the artwork's measured bounding box, not the frame.
- **Keying.** Both sources are gold on pure black JPEGs. Android's adaptive
  foreground and monochrome layers need transparency, so alpha is taken from
  each pixel's brightest channel and the colour is un-premultiplied back to
  full saturation. Near-black is forced to fully transparent, otherwise JPEG
  ringing leaves a grey haze around the mountain.
- **Safe zone.** An adaptive icon is a 108dp canvas with only the middle 72dp
  guaranteed visible — a circular mask eats the rest. Foreground and monochrome
  art is therefore drawn at 58% of the canvas, comfortably inside that 66.7%.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "assets" / "brand"
OUT = ROOT / "assets" / "images"

# Below this, a channel is JPEG noise in the black field rather than artwork.
BLACK_FLOOR = 12


def artwork(path: Path) -> Image.Image:
    """Load source art, key the black field out, and crop to the art itself."""
    source = Image.open(path).convert("RGB")
    pixels = source.load()
    width, height = source.size
    keyed = Image.new("RGBA", source.size, (0, 0, 0, 0))
    out = keyed.load()
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            alpha = max(r, g, b)
            if alpha <= BLACK_FLOOR:
                continue
            scale = 255 / alpha
            out[x, y] = (
                min(255, round(r * scale)),
                min(255, round(g * scale)),
                min(255, round(b * scale)),
                alpha,
            )
    return keyed.crop(keyed.getbbox())


def centred(art: Image.Image, canvas: int, coverage: float, background=(0, 0, 0, 0)):
    """Scale `art` to `coverage` of a square canvas and centre it there."""
    target = canvas * coverage
    scale = min(target / art.width, target / art.height)
    resized = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), background)
    out.paste(resized, ((canvas - resized.width) // 2, (canvas - resized.height) // 2), resized)
    return out


def main() -> None:
    mark = artwork(BRAND / "mark.jpeg")
    wordmark = artwork(BRAND / "wordmark.jpeg")

    # iOS and the web share one square icon. iOS forbids alpha in a launcher
    # icon, so this is the one output flattened back onto its black field.
    icon = centred(mark, 1024, 0.78, background=(0, 0, 0, 255))
    icon.convert("RGB").save(OUT / "icon.png")

    # Android draws the foreground over `adaptiveIcon.backgroundColor`.
    centred(mark, 1024, 0.58).save(OUT / "android-icon-foreground.png")

    # Themed icons (Android 13+) take shape from alpha only; colour is ignored,
    # so a flat white silhouette is the honest input.
    silhouette = centred(mark, 1024, 0.58)
    white = Image.new("RGBA", silhouette.size, (255, 255, 255, 0))
    white.putalpha(silhouette.getchannel("A"))
    white.save(OUT / "android-icon-monochrome.png")

    # The splash is the wordmark lockup centred on black by expo-splash-screen,
    # so it ships transparent and unpadded — `imageWidth` in app.json sizes it.
    wordmark.save(OUT / "splash-icon.png")

    favicon = centred(mark, 64, 0.82, background=(0, 0, 0, 255))
    favicon.convert("RGB").save(OUT / "favicon.png")

    # The old background layer is replaced by a flat colour in app.json.
    stale = OUT / "android-icon-background.png"
    if stale.exists():
        stale.unlink()

    for name in ("icon.png", "android-icon-foreground.png", "android-icon-monochrome.png",
                 "splash-icon.png", "favicon.png"):
        written = Image.open(OUT / name)
        print(f"{name:34} {written.size[0]}x{written.size[1]} {written.mode}")


if __name__ == "__main__":
    main()
