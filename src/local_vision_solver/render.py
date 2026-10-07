from io import BytesIO
from pathlib import Path
import os

from PIL import Image, ImageDraw, ImageFont

from .config import RenderConfig
from .models import Block, Draft


class RenderingError(RuntimeError):
    pass


def answer_text(draft: Draft) -> str:
    def section(blocks: list[Block]) -> str:
        return "\n\n".join(("$$\n" + b.content + "\n$$") if b.kind == "math" else b.content
                            for b in blocks)
    return "\n\n".join(s for s in (section(draft.final_answer), section(draft.solution)) if s)


class CardRenderer:
    def __init__(self, config: RenderConfig, working_directory: Path):
        self.config = config
        self.working_directory = working_directory
        for path in (config.font_path, config.code_font_path):
            if not path.is_file():
                raise RenderingError(f"Local font missing: {path}. Configure fonts with English/Russian/Kazakh glyphs.")
        self.font = ImageFont.truetype(str(config.font_path), config.font_size)
        self.code_font = ImageFont.truetype(str(config.code_font_path), config.font_size - 6)
        self.footer_font = ImageFont.truetype(str(config.font_path), 28)
        self.content_width = config.width - 2 * config.margin
        self.line_height = int(config.font_size * 1.35)
        self.bottom = config.height - config.margin - 52
        if self.bottom < config.margin + self.line_height:
            raise RenderingError("Card height leaves no readable text area")
        os.environ.setdefault("MPLCONFIGDIR", str(working_directory / ".render-cache"))
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.ft2font import FT2Font
        self.text_glyphs = FT2Font(str(config.font_path)).get_charmap()
        self.code_glyphs = FT2Font(str(config.code_font_path)).get_charmap()

    def _mathtext(self, formula: str, size: int) -> Image.Image:
        from matplotlib.font_manager import FontProperties
        from matplotlib.mathtext import math_to_image
        from matplotlib import rc_context
        data = BytesIO()
        try:
            with rc_context({"savefig.transparent": True}):
                math_to_image("$" + formula + "$", data, prop=FontProperties(size=size / 2),
                              dpi=144, format="png", color="white")
            data.seek(0)
            image = Image.open(data).convert("RGBA")
        except (ValueError, RuntimeError) as exc:
            raise RenderingError(
                f"Unsupported formula in offline mathtext: {formula!r}. Revise to supported notation.") from exc
        bbox = image.getchannel("A").getbbox()
        return image.crop(bbox) if bbox else image

    def math_image(self, formula: str) -> Image.Image:
        engine = self._mathtext
        available_height = self.bottom - self.config.margin
        for size in range(self.config.font_size, self.config.minimum_math_font_size - 1, -2):
            image = engine(formula, size)
            if image.width <= self.content_width and image.height <= available_height:
                return image
        raise RenderingError("Equation is too large for a readable phone card. Split it into logical steps; "
                             "the full text/structured answer is preserved in this session.")

    def wrap(self, paragraph: str, font: ImageFont.FreeTypeFont) -> list[str]:
        # Character wrapping preserves every character, including code indentation and long words.
        if not paragraph:
            return [""]
        lines = []
        remaining = paragraph
        while remaining:
            if font.getlength(remaining) <= self.content_width:
                lines.append(remaining)
                break
            low, high = 1, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if font.getlength(remaining[:middle]) <= self.content_width:
                    low = middle
                else:
                    high = middle - 1
            count = low
            if font.getlength(remaining[:count]) > self.content_width:
                raise RenderingError("A text glyph exceeds card width")
            last_space = remaining[:count].rfind(" ")
            # Preserve whitespace rather than stripping it from the underlying result.
            if last_space > count // 2:
                count = last_space + 1
            lines.append(remaining[:count])
            remaining = remaining[count:]
        return lines

    def render(self, draft: Draft, destination: Path) -> list[dict]:
        if destination.exists():
            raise RenderingError("Card destination already exists; choose a new output directory")
        destination.mkdir(parents=True)
        language = draft.detected_language
        labels = {"en": ("Answer", "Solution"), "ru": ("Ответ", "Решение"), "kk": ("Жауап", "Шешім")}
        sections = []
        if draft.final_answer:
            sections.append((labels[language][0], draft.final_answer))
        sections.append((labels[language][1] if draft.final_answer else "", draft.solution))
        pages: list[tuple[Path, str]] = []
        for title, blocks in sections:
            canvas = Image.new("RGB", (self.config.width, self.config.height), "black")
            draw = ImageDraw.Draw(canvas)
            y = self.config.margin
            content_present = False

            def flush():
                nonlocal canvas, draw, y, content_present
                if content_present:
                    path = destination / f"answer_{len(pages) + 1:02d}.png"
                    canvas.save(path)
                    pages.append((path, title))
                canvas = Image.new("RGB", (self.config.width, self.config.height), "black")
                draw = ImageDraw.Draw(canvas)
                y = self.config.margin
                content_present = False

            if title:
                draw.text((self.config.margin, y), title, font=self.font, fill="#a6c8ff")
                y += self.line_height + 12
            for block in blocks:
                if block.kind == "math":
                    equation = self.math_image(block.content)
                    if y + equation.height + 18 > self.bottom:
                        flush()
                    canvas.paste(equation, (self.config.margin, y), equation)
                    y += equation.height + 24
                    content_present = True
                else:
                    font = self.code_font if block.kind == "code" else self.font
                    glyphs = self.code_glyphs if block.kind == "code" else self.text_glyphs
                    missing = {c for c in block.content if not c.isspace() and ord(c) not in glyphs}
                    if missing:
                        raise RenderingError(f"Configured font lacks required characters: {''.join(sorted(missing))}")
                    for paragraph in block.content.split("\n"):
                        for line in self.wrap(paragraph, font):
                            if y + self.line_height > self.bottom:
                                flush()
                            draw.text((self.config.margin, y), line, font=font, fill="white")
                            y += self.line_height
                            content_present = True
                    y += 18
            flush()
        manifest = []
        for index, (path, title) in enumerate(pages, 1):
            canvas = Image.open(path).convert("RGB")
            draw = ImageDraw.Draw(canvas)
            footer = f"{index}/{len(pages)}"
            draw.text((self.config.margin, self.config.height - self.config.margin - 30),
                      footer, font=self.footer_font, fill="#a0a0a0")
            filename = f"answer_{index:02d}.png"
            canvas.save(destination / filename)
            manifest.append({"index": index, "file": filename, "section": title,
                             "width": canvas.width, "height": canvas.height})
        return manifest
