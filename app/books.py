"""EPUB / FB2 parsing for the LCD book reader (reader.py).

load(path) -> Book with chapters of simple blocks:
    ("h", text)   heading
    ("p", text)   paragraph (whitespace normalised)
    ("sep", "")   empty line
    ("img", key)  image; Book.image_bytes(key) -> (bytes, name hint) or None

Supported: .epub, .fb2, .txt, and .zip archives with an .fb2, .epub or .txt inside
(or a zipped epub). FB2 in any encoding its XML declaration names (windows-1251, koi8-r, ...);
plain text in UTF-8, windows-1251 or KOI8-U/R. PDF is shown as pages by pdfdoc.py instead.
"""
import base64
import io
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote
import xml.etree.ElementTree as ET

MAX_CHAPTER_BLOCKS = 250  # split huge chapters so paging stays fast on a Zero


class Chapter:
    def __init__(self, title, blocks):
        self.title = title
        self.blocks = blocks
        self.chars = sum(len(t) for k, t in blocks if k in ("p", "h")) or 1


class Book:
    def __init__(self, path, title, author, chapters, images):
        self.path = path
        self.title = title or path.rsplit("/", 1)[-1]
        self.author = author or ""
        chapters = [c for c in chapters if c.blocks]
        self.chapters = _split_big(chapters) or [Chapter(self.title, [("p", "(порожня книжка)")])]
        self._images = images  # key -> callable returning (bytes, name hint)
        self.total_chars = sum(c.chars for c in self.chapters)

    def image_bytes(self, key):
        get = self._images.get(key)
        if get is None:
            return None
        try:
            return get()
        except Exception:
            return None


def _split_big(chapters):
    out = []
    for c in chapters:
        if len(c.blocks) <= MAX_CHAPTER_BLOCKS:
            out.append(c)
            continue
        for i in range(0, len(c.blocks), MAX_CHAPTER_BLOCKS):
            part = i // MAX_CHAPTER_BLOCKS + 1
            out.append(Chapter("%s (%d)" % (c.title, part) if part > 1 else c.title,
                               c.blocks[i:i + MAX_CHAPTER_BLOCKS]))
    return out


def _norm(text):
    return " ".join(text.split())


# ---------------------------------------------------------------- opening files

def load(path):
    low = path.lower()
    with open(path, "rb") as f:
        data = f.read()
    if low.endswith(".fb2"):
        return parse_fb2(data, path)
    if low.endswith(".txt"):
        return parse_txt(data, path)
    if zipfile.is_zipfile(io.BytesIO(data)):
        return _load_zip(data, path)
    raise ValueError("unsupported file")


def _load_zip(data, path):
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    if "META-INF/container.xml" in names:
        return parse_epub(z, path)
    for n in names:
        if n.lower().endswith(".fb2"):
            return parse_fb2(z.read(n), path)
    for n in names:
        if n.lower().endswith(".txt"):
            return parse_txt(z.read(n), path)
    for n in names:
        if n.lower().endswith(".epub"):
            return parse_epub(zipfile.ZipFile(io.BytesIO(z.read(n))), path)
    raise ValueError("no .fb2, .epub or .txt in the archive")


def is_book(name):
    low = name.lower()
    return low.endswith((".epub", ".fb2", ".zip", ".txt", ".pdf"))


# ---------------------------------------------------------------- FB2

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _href(el):
    for k, v in el.attrib.items():
        if _local(k) == "href":
            return v
    return None


def _decode_xml(data):
    head = data[:300].decode("ascii", "replace")
    m = re.search(r'encoding=["\']([A-Za-z0-9_\-]+)["\']', head)
    enc = m.group(1) if m else "utf-8"
    if data.startswith(b"\xef\xbb\xbf"):
        enc, data = "utf-8", data[3:]
    try:
        text = data.decode(enc, "replace")
    except LookupError:
        text = data.decode("utf-8", "replace")
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)


def parse_fb2(data, path):
    root = ET.fromstring(_decode_xml(data))
    title = author = ""
    cover = None
    binaries = {}
    for el in root.iter():
        name = _local(el.tag)
        if name == "binary" and el.get("id"):
            binaries[el.get("id")] = (el.text or "", el.get("content-type", ""))
    desc = next((e for e in root if _local(e.tag) == "description"), None)
    if desc is not None:
        ti = next((e for e in desc if _local(e.tag) == "title-info"), None)
        if ti is not None:
            for e in ti:
                n = _local(e.tag)
                if n == "book-title":
                    title = _norm("".join(e.itertext()))
                elif n == "author" and not author:
                    parts = {_local(x.tag): _norm("".join(x.itertext())) for x in e}
                    author = " ".join(p for p in (parts.get("first-name"), parts.get("last-name")) if p) \
                        or parts.get("nickname", "")
                elif n == "coverpage":
                    img = next((x for x in e.iter() if _local(x.tag) == "image"), None)
                    if img is not None and (_href(img) or "").startswith("#"):
                        cover = _href(img)[1:]

    chapters = []
    for body in (e for e in root if _local(e.tag) == "body"):
        notes = body.get("name") in ("notes", "comments")
        sections = [e for e in body if _local(e.tag) == "section"]
        lead = []  # blocks of the body before its first section (title, epigraph, images)
        for e in body:
            if _local(e.tag) == "section":
                break
            _fb2_blocks(e, lead)
        if not sections:
            chapters.append(Chapter(_first_heading(lead, title), lead))
            continue
        if lead:
            chapters.append(Chapter(_first_heading(lead, title), lead))
        for s in sections:
            blocks = []
            _fb2_blocks(s, blocks)
            ch_title = _first_heading(blocks, "Примітки" if notes else "Розділ %d" % (len(chapters) + 1))
            chapters.append(Chapter(ch_title, blocks))

    images = {k: (lambda v=v, k=k: (base64.b64decode(v[0]), _hint(k, v[1]))) for k, v in binaries.items()}
    if cover in images and chapters:
        chapters[0].blocks.insert(0, ("img", cover))
    return Book(path, title, author, chapters, images)


def _hint(name, ctype):
    if "png" in ctype or name.lower().endswith(".png"):
        return "x.png"
    if "gif" in ctype or name.lower().endswith(".gif"):
        return "x.gif"
    return "x.jpg"


def _first_heading(blocks, default):
    for k, t in blocks:
        if k == "h" and t:
            return t
    return default


def _fb2_blocks(el, out):
    name = _local(el.tag)
    if name in ("title", "subtitle"):
        text = " ".join(_norm("".join(p.itertext())) for p in el if _local(p.tag) in ("p",)) \
            or _norm("".join(el.itertext()))
        if text:
            out.append(("h", text))
    elif name in ("p", "v", "text-author"):
        text = _norm("".join(el.itertext()))
        if text:
            out.append(("p", text))
        for img in (x for x in el.iter() if _local(x.tag) == "image"):  # inline images
            href = _href(img) or ""
            if href.startswith("#"):
                out.append(("img", href[1:]))
    elif name == "empty-line":
        out.append(("sep", ""))
    elif name == "image":
        href = _href(el) or ""
        if href.startswith("#"):
            out.append(("img", href[1:]))
    elif name == "table":
        for tr in (x for x in el.iter() if _local(x.tag) == "tr"):
            cells = [_norm("".join(td.itertext())) for td in tr]
            if any(cells):
                out.append(("p", " | ".join(cells)))
    elif name in ("section", "poem", "stanza", "cite", "epigraph", "annotation", "body"):
        for child in el:
            _fb2_blocks(child, out)
        if name in ("stanza", "poem"):
            out.append(("sep", ""))


# ---------------------------------------------------------------- plain text

# a short line like this starts a chapter
_HEADING = re.compile(r"^(глава|розділ|раздел|частина|часть|chapter|part|книга|book|пролог|епілог|эпилог|prologue|epilogue)\b"
                      r"|^[IVXLC]+\.?$|^\d{1,3}\.?$", re.IGNORECASE)


def _decode_text(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # windows-1251 or KOI8-U (a superset of KOI8-R): the one that gives more lowercase Cyrillic letters wins
    best, score = None, -1
    for enc in ("cp1251", "koi8_u"):
        text = data.decode(enc, "replace")
        n = sum(1 for ch in text[:20000] if "а" <= ch <= "я" or ch in "іїєґ")
        if n > score:
            best, score = text, n
    return best


def parse_txt(data, path):
    lines = _decode_text(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blank = sum(1 for ln in lines if not ln.strip())
    # paragraphs: separated by blank lines (hard-wrapped text), or one per line
    by_blank = blank > len(lines) / 8 and blank > 0
    paras, buf = [], []
    for ln in lines:
        if not ln.strip():
            if buf:
                paras.append(" ".join(buf))
                buf = []
        elif by_blank:
            buf.append(ln.strip())
        else:
            paras.append(ln.strip())
    if buf:
        paras.append(" ".join(buf))
    title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    chapters, blocks, ch_title = [], [], title
    for p in paras:
        p = _norm(p)
        if len(p) < 60 and _HEADING.match(p):
            if blocks:
                chapters.append(Chapter(ch_title, blocks))
            ch_title, blocks = p, [("h", p)]
        else:
            blocks.append(("p", p))
    if blocks:
        chapters.append(Chapter(ch_title, blocks))
    return Book(path, title, "", chapters, {})


# ---------------------------------------------------------------- EPUB

def _xml(z, name):
    return ET.fromstring(z.read(name))


def parse_epub(z, path):
    container = _xml(z, "META-INF/container.xml")
    rootfile = next(e for e in container.iter() if _local(e.tag) == "rootfile").get("full-path")
    opf = _xml(z, rootfile)
    base = posixpath.dirname(rootfile)
    names = set(z.namelist())

    title = author = ""
    cover_id = None
    for e in opf.iter():
        n = _local(e.tag)
        if n == "title" and not title:
            title = _norm("".join(e.itertext()))
        elif n == "creator" and not author:
            author = _norm("".join(e.itertext()))
        elif n == "meta" and e.get("name") == "cover":
            cover_id = e.get("content")

    manifest = {}
    cover_href = None
    for e in opf.iter():
        if _local(e.tag) == "item":
            href = posixpath.normpath(posixpath.join(base, unquote(e.get("href", ""))))
            manifest[e.get("id")] = (href, e.get("media-type", ""))
            if e.get("id") == cover_id or "cover-image" in (e.get("properties") or ""):
                cover_href = href
    spine = [manifest[e.get("idref")][0] for e in opf.iter()
             if _local(e.tag) == "itemref" and e.get("idref") in manifest
             and e.get("linear", "yes") != "no"]

    def image(name):
        return lambda: (z.read(name), name)
    images = {n: image(n) for n in names if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))}

    chapters = []
    for href in spine:
        if href not in names:
            continue
        parser = _XhtmlBlocks(posixpath.dirname(href), names)
        parser.feed(z.read(href).decode("utf-8", "replace"))
        parser.close()
        blocks = parser.finish()
        if not any(k != "sep" for k, _ in blocks):
            continue
        chapters.append(Chapter(_first_heading(blocks, "Розділ %d" % (len(chapters) + 1)), blocks))
    if cover_href in images and chapters and not any(k == "img" for k, _ in chapters[0].blocks[:3]):
        chapters.insert(0, Chapter(title or "Обкладинка", [("img", cover_href)]))
    return Book(path, title, author, chapters, images)


class _XhtmlBlocks(HTMLParser):
    BLOCK = {"p", "div", "li", "blockquote", "tr", "dt", "dd", "pre", "section", "article",
             "figure", "figcaption", "td", "th", "table", "ul", "ol", "body"}
    HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self, base, names):
        super().__init__(convert_charrefs=True)
        self.base, self.names = base, names
        self.blocks, self.buf = [], []
        self.heading = 0
        self.skip = 0

    def _flush(self):
        text = _norm("".join(self.buf))
        self.buf = []
        if text:
            self.blocks.append(("h" if self.heading else "p", text))

    def _img(self, src):
        if not src or src.startswith("data:"):
            return
        name = posixpath.normpath(posixpath.join(self.base, unquote(src.split("#")[0])))
        if name in self.names:
            self._flush()
            self.blocks.append(("img", name))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.HEAD:
            self._flush()
            self.heading += 1
        elif tag in self.BLOCK:
            self._flush()
        elif tag == "br":
            self._flush()
        elif tag == "hr":
            self._flush()
            self.blocks.append(("sep", ""))
        elif tag == "img":
            self._img(a.get("src"))
        elif tag == "image":  # svg cover pages
            self._img(a.get("xlink:href") or a.get("href"))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.SKIP:
            self.skip -= 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.HEAD:
            self._flush()
            self.heading = max(0, self.heading - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def finish(self):
        self._flush()
        return self.blocks
