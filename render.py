"""Render termfetch.svg from termfetch.json, with the photo backdrop blanked per cell.

termfetch samples the photo with LANCZOS, which bleeds the backdrop into faint glyphs
around the silhouette. Here the backdrop is found by flood fill, turned into a per-cell
mask, and every backdrop cell is drawn as a space.
"""
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from termfetch import art, cli, svg, theme

CONFIG = Path("termfetch.json")
WALL_SEEDS = [(0, 0), (511, 0), (0, 300), (511, 300), (256, 0)]
WALL_TOLERANCE = 38
MAX_WALL_SHARE = 0.5
# Glyphs dimmer than this vanish into the #0d1117 card and read as dirt, so they are lifted.
MIN_GLYPH_LUMA = 0x58


def wall_mask(photo: Image.Image) -> Image.Image:
    flooded = photo.copy()
    for seed in WALL_SEEDS:
        ImageDraw.floodfill(flooded, seed, (255, 0, 255), thresh=WALL_TOLERANCE)
    wall = ImageChops.difference(flooded, photo).convert("L").point(lambda v: 255 if v else 0)
    # Close JPEG pinholes the fill skipped.
    return wall.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))


def subject_cells(wall: Image.Image, cols: int, rows: int) -> set[tuple[int, int]]:
    share = wall.resize((cols, rows), Image.BOX)
    cells = {(x, y) for y in range(rows) for x in range(cols)
             if share.getpixel((x, y)) <= 255 * MAX_WALL_SHARE}
    # Largest 4-connected blob wins: specks of wall the fill missed are dropped.
    best, seen = set(), set()
    for start in cells:
        if start in seen:
            continue
        blob, stack = set(), [start]
        while stack:
            cell = stack.pop()
            if cell in seen or cell not in cells:
                continue
            seen.add(cell)
            blob.add(cell)
            x, y = cell
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        best = max(best, blob, key=len)
    return best


def luma(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def lift(color: str) -> str:
    """Raise a dim colour to MIN_GLYPH_LUMA, blending toward grey to keep its hue."""
    current = luma(color)
    if current >= MIN_GLYPH_LUMA:
        return color
    t = (MIN_GLYPH_LUMA - current) / (255 - current)
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(c + (255 - c) * t) for c in (r, g, b))


def main() -> None:
    cfg = cli.load_config(CONFIG)
    photo = Image.open(cfg["image"]).convert("RGB")
    wall = wall_mask(photo)
    crop = tuple(cfg["imageCrop"]) if cfg["imageCrop"] else None
    with tempfile.NamedTemporaryFile(suffix=".png") as masked:
        Image.composite(Image.new("RGB", photo.size), photo, wall).save(masked.name)
        picture = art.render(
            masked.name, cols=cfg["imageCols"], charset=cfg["charset"], colored=cfg["coloredImage"],
            crop=crop, char_aspect=svg.CHAR_WIDTH_RATIO, contrast=cfg["contrast"],
            brightness=cfg["brightness"], gamma=cfg["gamma"], color_step=cfg["colorStep"],
            invert=cfg["invert"],
        )
    if crop:
        x, y, w, h = crop
        wall = wall.crop((x, y, x + w, y + h))
    keep = subject_cells(wall, picture.width, picture.height)
    picture = art.Art([
        [art.Cell(cell.char, lift(cell.color)) if (x, y) in keep else art.Cell(" ", cell.color)
         for x, cell in enumerate(row)]
        for y, row in enumerate(picture.rows)
    ])

    layout = svg.Layout(
        font_size=cfg["fontSize"], chrome=cfg["chrome"], key_width=cfg["keyWidth"],
        panel_align=cfg["panelAlign"], leaders=cfg["leaders"], panel_chars=cfg["panelChars"],
        title_rule=cfg["titleRule"],
    )
    active = theme.get(cfg["theme"]).merged(cfg["colors"])
    Path("termfetch.svg").write_text(svg.build(picture, cli.build_sections(cfg, {}), active, layout, ""))
    print(picture.as_text())


main()
