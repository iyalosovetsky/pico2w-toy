"""PDF pages for the LCD book reader, rendered by poppler's pdftoppm / pdfinfo.

PdfDoc(path).render(page, width) -> PNG bytes of the page's content (white margins
cropped), scaled so the content is `width` pixels wide. render() caches a few pages and
prefetch() renders one in the background, so the next page is usually ready.
"""
import io
import subprocess
import threading

from PIL import Image

MARGIN = 0.015  # kept around the content, as a fraction of the page


def _run(args, timeout=60):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, check=True).stdout


class PdfDoc:
    def __init__(self, path):
        self.path = path
        info = {}
        for line in _run(["pdfinfo", path], 30).decode("utf-8", "replace").splitlines():
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
        self.pages = int(info.get("Pages", "0"))
        if self.pages < 1:
            raise ValueError("no pages")
        self.title = info.get("Title", "")
        self.author = info.get("Author", "")
        self._boxes = {}     # page -> (x0, y0, x1, y1 as page fractions, page h/w)
        self._cache = {}     # (page, width) -> png bytes
        self._order = []
        self._lock = threading.Lock()
        self._busy = {}      # (page, width) -> Thread

    def box(self, page):
        """Content box of a page (fractions) and the page's aspect ratio (h / w)."""
        if page not in self._boxes:
            png = _run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-png", "-gray",
                        "-scale-to-x", "300", "-scale-to-y", "-1", self.path])
            img = Image.open(io.BytesIO(png)).convert("L")
            w, h = img.size
            bbox = img.point(lambda v: 255 if v < 235 else 0).getbbox() or (0, 0, w, h)
            x0, y0 = max(0.0, bbox[0] / w - MARGIN), max(0.0, bbox[1] / h - MARGIN)
            x1, y1 = min(1.0, bbox[2] / w + MARGIN), min(1.0, bbox[3] / h + MARGIN)
            self._boxes[page] = (x0, y0, x1, y1, h / w)
        return self._boxes[page]

    def content_aspect(self, page):
        x0, y0, x1, y1, a = self.box(page)
        return (y1 - y0) * a / (x1 - x0)

    def _render(self, page, width):
        x0, y0, x1, y1, a = self.box(page)
        full_w = max(1, round(width / (x1 - x0)))
        full_h = round(full_w * a)
        crop = [round(x0 * full_w), round(y0 * full_h), width, max(1, round((y1 - y0) * full_h))]
        return _run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-png",
                     "-scale-to-x", str(full_w), "-scale-to-y", str(full_h),
                     "-x", str(crop[0]), "-y", str(crop[1]), "-W", str(crop[2]), "-H", str(crop[3]),
                     self.path])

    def _store(self, key, png):
        with self._lock:
            if key not in self._cache:
                self._cache[key] = png
                self._order.append(key)
                while len(self._order) > 4:
                    self._cache.pop(self._order.pop(0), None)

    def cached(self, page, width):
        with self._lock:
            return self._cache.get((page, width))

    def render(self, page, width):
        key = (page, width)
        t = self._busy.get(key)
        if t is not None:
            t.join()
        png = self.cached(page, width)
        if png is None:
            png = self._render(page, width)
            self._store(key, png)
        return png

    def prefetch(self, page, width):
        key = (page, width)
        if not 1 <= page <= self.pages or self.cached(page, width) or key in self._busy:
            return

        def work():
            try:
                self._store(key, self._render(page, width))
            except Exception:
                pass
            finally:
                self._busy.pop(key, None)
        t = threading.Thread(target=work, daemon=True)
        self._busy[key] = t
        t.start()
