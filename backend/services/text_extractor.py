# backend/services/text_extractor.py — Multi-format Document Text Extractor
import os
import re
import json
import base64
import socket
import ipaddress
import urllib.parse
import urllib.request
import urllib.error
import html.parser
from pathlib import Path
from typing import List, Tuple, Optional

import pymupdf as fitz  # PyMuPDF

try:
    import docx
except ImportError:
    docx = None

from backend.config import (
    GEMINI_API_KEY,
    GEMINI_URL,
    GEMINI_VISION_MODEL,
    OLLAMA_URL,
    OLLAMA_VISION_MODEL,
    VISION_BACKEND,
    logger,
)


def extract_pdf_pages(filepath: str) -> List[dict]:
    """Extract text from each page of a PDF. Returns list of {page, text}."""
    pages = []
    try:
        doc = fitz.open(filepath)
    except Exception:
        logger.info("Could not open PDF %s (corrupt, encrypted, or not a real PDF)", filepath, exc_info=True)
        return []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if text:
            pages.append({"page": page_num, "text": text})
    doc.close()
    return pages


def extract_txt_pages(filepath: str) -> List[dict]:
    """Treat a .txt or .md file as logical sections separated by blank lines."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read().strip()
    sections = [s.strip() for s in re.split(r"\n{3,}", text) if s.strip()]
    if not sections:
        sections = [text]
    return [{"page": i + 1, "text": s} for i, s in enumerate(sections)]


_OCR_PROMPT = (
    "Extract all text, table content, diagram descriptions, titles, bullet points, "
    "and key information from this image into clean, structured Markdown text."
)


def _gemini_vision_ocr(img_b64: str, mime_type: str, filename: str) -> str:
    """Vision OCR via Gemini's generateContent API (multimodal inline_data)."""
    url = f"{GEMINI_URL}/models/{GEMINI_VISION_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": img_b64}},
                    {"text": _OCR_PROMPT},
                ]
            }
        ],
        "generationConfig": {"temperature": 0}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    extracted_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    logger.info("🖼️ Gemini Vision OCR extracted %d characters from image %s", len(extracted_text), filename)
    return extracted_text


def _ollama_vision_ocr(img_b64: str, filename: str) -> str:
    """Vision OCR via a locally-running Ollama vision model."""
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": OLLAMA_VISION_MODEL,
        "prompt": _OCR_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    extracted_text = (data.get("response") or "").strip()
    logger.info("🖼️ Ollama (%s) Vision OCR extracted %d characters from image %s",
                OLLAMA_VISION_MODEL, len(extracted_text), filename)
    return extracted_text


def extract_image_pages(filepath: str) -> List[dict]:
    """Extract text and visual content from images via Vision OCR."""
    ext = filepath.rsplit(".", 1)[-1].lower()
    mime_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")

    filename = Path(filepath).name

    if VISION_BACKEND == "gemini" and not GEMINI_API_KEY:
        logger.warning("⚠️ Gemini API Key missing for Image Vision OCR: %s", filename)
        return [{"page": 1, "text": f"Document Image: {filename}\nNote: Configure GEMINI_API_KEY to enable full Vision OCR extraction."}]

    try:
        with open(filepath, "rb") as img_file:
            img_b64 = base64.b64encode(img_file.read()).decode("utf-8")

        if VISION_BACKEND == "ollama":
            extracted_text = _ollama_vision_ocr(img_b64, filename)
        else:
            extracted_text = _gemini_vision_ocr(img_b64, mime_type, filename)

        return [{"page": 1, "text": f"# Image OCR Content: {filename}\n\n{extracted_text}"}]
    except Exception as exc:
        backend_label = "Ollama" if VISION_BACKEND == "ollama" else "Gemini"
        logger.error("❌ %s Vision OCR failed for %s: %s", backend_label, filename, exc, exc_info=True)
        return [{"page": 1, "text": f"Image Document: {filename}\n(Error during image text extraction)"}]


def extract_docx_pages(filepath: str) -> List[dict]:
    """Extract text and tables from Word (.docx / .doc) documents."""
    try:
        if docx is None:
            raise ImportError("python-docx package not installed")
        doc = docx.Document(filepath)
        full_text = []
        for p in doc.paragraphs:
            if p.text.strip():
                full_text.append(p.text.strip())
        for t in doc.tables:
            for row in t.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    full_text.append(f"| {row_text} |")
        text = "\n\n".join(full_text)
        sections = [s.strip() for s in re.split(r"\n{3,}", text) if s.strip()] or [text]
        return [{"page": i + 1, "text": s} for i, s in enumerate(sections)]
    except Exception as exc:
        logger.info("Falling back to plain text read for Word document %s: %s", filepath, exc)
        return extract_txt_pages(filepath)


def extract_data_pages(filepath: str, ext: str) -> List[dict]:
    """Extract CSV, TSV, JSON, XML, YAML data files as structured Markdown."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read().strip()

    if ext in ("csv", "tsv"):
        lines = content.splitlines()
        delimiter = "\t" if ext == "tsv" else ","
        formatted = []
        for line in lines:
            parts = line.split(delimiter)
            formatted.append(" | ".join(p.strip() for p in parts))
        text = "```table\n" + "\n".join(formatted) + "\n```"
    elif ext in ("json", "yaml", "yml", "xml"):
        text = f"```{ext}\n{content}\n```"
    else:
        text = content

    return [{"page": 1, "text": text}]


def extract_code_pages(filepath: str, ext: str) -> List[dict]:
    """Extract source code files wrapped in code blocks."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read().strip()
    wrapped = f"```{ext}\n{code}\n```"
    return [{"page": 1, "text": wrapped}]


def extract_document_pages(filepath: str, ext: str) -> List[dict]:
    """Universal text extractor supporting PDF, TXT, MD, DOCX, CSV/JSON, Code, and Images."""
    ext = ext.lower()
    if ext == "pdf":
        return extract_pdf_pages(filepath)
    elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif"):
        return extract_image_pages(filepath)
    elif ext in ("docx", "doc"):
        return extract_docx_pages(filepath)
    elif ext in ("csv", "tsv", "json", "yaml", "yml", "xml"):
        return extract_data_pages(filepath, ext)
    elif ext in ("py", "js", "ts", "jsx", "tsx", "html", "css", "c", "cpp", "h", "hpp", "java", "go", "rs", "php", "sql", "sh", "bat", "ps1"):
        return extract_code_pages(filepath, ext)
    else:
        return extract_txt_pages(filepath)


# Web page extraction
_IGNORE_TAGS = {"script", "style", "noscript", "svg", "canvas", "nav", "header", "footer"}


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.in_title = False
        self.title = None
        self.parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORE_TAGS:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "blockquote"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _IGNORE_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == "title":
            self.in_title = False
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "blockquote"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_title:
            self.title = data.strip()
            return
        self.parts.append(data)

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


def _extract_web_title(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    return parser.title or ""


def _extract_web_visible_text(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    return parser.get_text()


MAX_URL_FETCH_BYTES = 10 * 1024 * 1024
URL_FETCH_TIMEOUT = 15


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _is_private_ip(ip_str: str) -> bool:
    return not _is_public_ip(ip_str)



def _validate_url_is_public(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// URLs are allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    h_lower = hostname.lower()
    if (h_lower in ("localhost", "0.0.0.0", "127.0.0.1", "::1", "169.254.169.254")
            or h_lower.endswith(".local") or h_lower.endswith(".internal")):
        raise ValueError(f"URL hostname '{hostname}' resolves to a non-public/internal address — refusing to fetch")

    if parsed.port and parsed.port not in (80, 443, 8080, 8443):
        raise ValueError(f"Port {parsed.port} is not allowed for web document ingestion")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    if not infos:
        raise ValueError(f"Could not resolve hostname '{hostname}' to an IP address")

    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        if not _is_public_ip(ip_str):
            raise ValueError(f"URL '{hostname}' resolves to a non-public address ({ip_str}) — refusing to fetch")


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_web_page(url: str, max_redirects: int = 5) -> Tuple[str, str]:
    opener = urllib.request.build_opener(_NoAutoRedirect)
    current = url
    raw = None

    for _ in range(max_redirects + 1):
        _validate_url_is_public(current)
        req = urllib.request.Request(
            current,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 AskMyDocs/1.0"},
        )
        try:
            with opener.open(req, timeout=URL_FETCH_TIMEOUT) as resp:
                raw_bytes = resp.read(MAX_URL_FETCH_BYTES + 1)
                if len(raw_bytes) > MAX_URL_FETCH_BYTES:
                    raise ValueError(f"Page exceeded {MAX_URL_FETCH_BYTES // (1024 * 1024)} MB size limit")
                raw = raw_bytes.decode("utf-8", errors="ignore")
            break
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    raise ValueError(f"Redirect ({e.code}) with no Location header") from e
                current = urllib.parse.urljoin(current, location)
                continue
            raise
    else:
        raise ValueError(f"Too many redirects (>{max_redirects})")

    if raw is None:
        raise ValueError("Too many redirects")

    parser = _TextExtractor()
    parser.feed(raw)
    title = parser.title or urllib.parse.urlparse(current).netloc
    text = parser.get_text()
    return title, text
