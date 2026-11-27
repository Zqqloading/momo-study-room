"""Markdown/HTML 解析与父子切块（v1 摄取；无网络、无 DB）。

v0 不调用这里；`python -m core.ingest --dry-run` 用它产出 chunks.json。
切块规则见 `docs/designs/knowledge-base-v0.1.md` KB-21/KB-22：
- 父块按标题切，600-1000 token；无标题按段落兜底；
- 子块按段落切，150-250 token，10% 重叠；少于 80 token 合并；
- 代码块/表格不切，超限标 flag；
- token 用字符近似：中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path

import yaml

PARENT_MIN = 600
PARENT_MAX = 1000
CHILD_MIN = 150
CHILD_MAX = 250
CHILD_BASE_MAX = 225  # 给 10% 重叠留余量，保证最终 <= CHILD_MAX
OVERLAP_RATIO = 0.10

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}
_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class IngestError(ValueError):
    """材料无法读取或格式不支持；错误信息要能指出文件。"""


@dataclass(frozen=True, slots=True)
class Block:
    kind: str  # heading | paragraph | code | table
    text: str
    level: int = 0
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedMaterial:
    path: str
    title: str
    format: str  # md | html
    source_url: str | None
    blocks: tuple[Block, ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    material_id: str
    material_version: int
    level: str  # parent | child
    parent_id: str | None
    heading_path: str
    text: str
    token_count: int
    ordinal: int
    content_hash: str
    source_url: str = ""
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "material_id": self.material_id,
            "material_version": self.material_version,
            "level": self.level,
            "parent_id": self.parent_id,
            "heading_path": self.heading_path,
            "text": self.text,
            "token_count": self.token_count,
            "ordinal": self.ordinal,
            "content_hash": self.content_hash,
            "source_url": self.source_url,
            "flags": list(self.flags),
        }


def count_tokens(text: str) -> int:
    """字符近似：中文按字，非中文非空白按 4 字符 1 token。"""
    if not text.strip():
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = sum(1 for ch in text if not ch.isspace() and not _CJK_RE.match(ch))
    return cjk + (rest + 3) // 4


def parse_material(path: str | Path) -> ParsedMaterial:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise IngestError(f"材料不存在或不是文件：{file_path}")
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(f"材料不是 UTF-8：{file_path}") from exc
    if not text.strip():
        raise IngestError(f"材料是空文件：{file_path}")

    suffix = file_path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return _parse_markdown(file_path, text)
    if suffix in {".html", ".htm"}:
        return _parse_html(file_path, text)
    raise IngestError(f"不支持的格式 {suffix!r}：{file_path}（只收 .md/.html）")


def _title_from_path(path: Path) -> str:
    return path.stem.strip() or path.name


def material_id(path: str | Path) -> str:
    return _slug(_title_from_path(Path(path)))


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", text.strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "material"


def _parse_markdown(path: Path, text: str) -> ParsedMaterial:
    lines = text.splitlines()
    meta, start = _front_matter(lines)
    blocks: list[Block] = []
    heading_path: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(Block("paragraph", body, heading_path=tuple(h for _, h in heading_path)))
        buffer.clear()

    index = start
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence = re.match(r"^(```+|~~~+)", stripped)
        if fence:
            flush()
            marker = fence.group(1)[:3]
            code: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            blocks.append(
                Block("code", "\n".join(code).strip(), heading_path=tuple(h for _, h in heading_path))
            )
            index += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            while heading_path and heading_path[-1][0] >= level:
                heading_path.pop()
            heading_path.append((level, heading.group(2).strip()))
            blocks.append(
                Block(
                    "heading",
                    heading.group(2).strip(),
                    level=level,
                    heading_path=tuple(h for _, h in heading_path),
                )
            )
            index += 1
            continue

        if _is_table_start(lines, index):
            flush()
            table: list[str] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table.append(lines[index].strip())
                index += 1
            blocks.append(
                Block("table", "\n".join(table), heading_path=tuple(h for _, h in heading_path))
            )
            continue

        if not stripped:
            flush()
            index += 1
            continue

        buffer.append(line.rstrip())
        index += 1

    flush()
    return ParsedMaterial(
        path=str(path),
        title=_title_from_path(path),
        format="md",
        source_url=_as_text(meta.get("source_url")),
        blocks=tuple(blocks),
        tags=_tags(meta.get("tags")),
    )


def _front_matter(lines: list[str]) -> tuple[dict[str, object], int]:
    if len(lines) < 2 or lines[0].strip() != "---":
        return {}, 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = yaml.safe_load("\n".join(lines[1:index])) or {}
            if not isinstance(raw, dict):
                raise IngestError("YAML front matter 必须是对象")
            return raw, index + 1
    return {}, 0


def _is_table_start(lines: list[str], index: int) -> bool:
    if "|" not in lines[index] or index + 1 >= len(lines):
        return False
    return _is_table_separator(lines[index + 1])


def _is_table_separator(line: str) -> bool:
    value = line.strip()
    return "|" in value and bool(re.match(r"^\|?[\s:|-]+\|?$", value))


def _as_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list["_Node | str"] = []


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.title = ""
        self.canonical = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag == "title":
            self._in_title = True
        if tag == "link" and node.attrs.get("rel", "").lower() == "canonical":
            self.canonical = node.attrs.get("href", "") or self.canonical
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag == "link" and node.attrs.get("rel", "").lower() == "canonical":
            self.canonical = node.attrs.get("href", "") or self.canonical

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        self.stack[-1].children.append(data)


def _parse_html(path: Path, text: str) -> ParsedMaterial:
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()

    content = (
        _find(builder.root, "article")
        or _find(builder.root, "main")
        or _find(builder.root, "body")
        or builder.root
    )
    blocks: list[Block] = []
    _flatten_html(content, blocks, [])
    return ParsedMaterial(
        path=str(path),
        title=(builder.title.strip() or _title_from_path(path)),
        format="html",
        source_url=builder.canonical.strip() or None,
        blocks=tuple(blocks),
    )


def _find(node: _Node, tag: str) -> _Node | None:
    if node.tag == tag:
        return node
    for child in node.children:
        if isinstance(child, _Node):
            found = _find(child, tag)
            if found is not None:
                return found
    return None


def _node_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_TAGS:
            parts.append(_node_text(child))
    return " ".join("".join(parts).split())


def _flatten_html(node: _Node, blocks: list[Block], heading_path: list[tuple[int, str]]) -> None:
    buffer: list[str] = []

    def flush() -> None:
        body = " ".join("".join(buffer).split())
        if body:
            blocks.append(
                Block("paragraph", body, heading_path=tuple(t for _, t in heading_path))
            )
        buffer.clear()

    for child in node.children:
        if isinstance(child, str):
            buffer.append(child)
            continue
        if child.tag in _SKIP_TAGS:
            continue
        if child.tag in _HEADING_TAGS:
            flush()
            level = _HEADING_TAGS[child.tag]
            title = _node_text(child)
            if not title:
                continue
            while heading_path and heading_path[-1][0] >= level:
                heading_path.pop()
            heading_path.append((level, title))
            blocks.append(
                Block(
                    "heading",
                    title,
                    level=level,
                    heading_path=tuple(text for _, text in heading_path),
                )
            )
        elif child.tag in {"p", "li", "blockquote"}:
            flush()
            body = _node_text(child)
            if body:
                blocks.append(
                    Block("paragraph", body, heading_path=tuple(t for _, t in heading_path))
                )
        elif child.tag == "pre":
            flush()
            code = "\n".join(
                part for part in _raw_text(child).splitlines() if part.strip()
            )
            if code:
                blocks.append(
                    Block("code", code, heading_path=tuple(t for _, t in heading_path))
                )
        elif child.tag == "table":
            flush()
            body = _html_table_text(child)
            if body:
                blocks.append(
                    Block("table", body, heading_path=tuple(t for _, t in heading_path))
                )
        else:
            flush()
            _flatten_html(child, blocks, heading_path)
    flush()


def _raw_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_TAGS:
            parts.append(_raw_text(child))
    return "".join(parts)


def _find_all(node: _Node, tag: str) -> list[_Node]:
    found: list[_Node] = []
    if node.tag == tag:
        found.append(node)
    for child in node.children:
        if isinstance(child, _Node):
            found.extend(_find_all(child, tag))
    return found


def _html_table_text(node: _Node) -> str:
    """把 HTML 表格转成管道表文本，让超长表格能按行组切。"""
    rows: list[str] = []
    for tr in _find_all(node, "tr"):
        cells = [
            _node_text(child)
            for child in tr.children
            if isinstance(child, _Node) and child.tag in {"td", "th"}
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return _node_text(node)
    if len(rows) == 1:
        return rows[0]
    columns = rows[0].count("|") - 1
    separator = "|" + " --- |" * columns
    return "\n".join([rows[0], separator, *rows[1:]])


def chunk_material(
    material: ParsedMaterial, *, version: int = 1, mid: str | None = None
) -> tuple[Chunk, ...]:
    mid = mid or material_id(material.path)
    source_url = material.source_url or f"local://{material.path}"
    blocks = _expand_blocks(material.blocks, PARENT_MAX)
    parents = _make_parents(blocks)

    chunks: list[Chunk] = []
    ordinal = 1
    for parent_index, (heading_path, parent_blocks, flags) in enumerate(parents, start=1):
        parent_text = "\n".join(block.text for block in parent_blocks).strip()
        parent_id = f"{mid}-v{version}-parent-{parent_index:03d}"
        chunks.append(
            Chunk(
                id=parent_id,
                material_id=mid,
                material_version=version,
                level="parent",
                parent_id=None,
                heading_path=" > ".join(heading_path),
                text=parent_text,
                token_count=count_tokens(parent_text),
                ordinal=ordinal,
                content_hash=_hash(parent_text),
                source_url=source_url,
                flags=tuple(flags),
            )
        )
        ordinal += 1

        for child_text, child_flags, _child_kind, child_heading in _make_children(parent_blocks):
            child_id = f"{mid}-v{version}-child-{ordinal:03d}"
            chunks.append(
                Chunk(
                    id=child_id,
                    material_id=mid,
                    material_version=version,
                    level="child",
                    parent_id=parent_id,
                    heading_path=" > ".join(child_heading),
                    text=child_text,
                    token_count=count_tokens(child_text),
                    ordinal=ordinal,
                    content_hash=_hash(child_text),
                    source_url=source_url,
                    flags=tuple(child_flags),
                )
            )
            ordinal += 1

    return tuple(chunks)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _expand_blocks(blocks: tuple[Block, ...], max_tokens: int) -> list[Block]:
    expanded: list[Block] = []
    for block in blocks:
        if block.kind == "paragraph" and count_tokens(block.text) > max_tokens:
            for part in _split_text(block.text, max_tokens):
                expanded.append(replace(block, text=part))
        else:
            expanded.append(block)
    return expanded


def _make_parents(blocks: list[Block]) -> list[tuple[tuple[str, ...], list[Block], list[str]]]:
    parents: list[tuple[tuple[str, ...], list[Block], list[str]]] = []
    current: list[Block] = []
    current_path: tuple[str, ...] = ()
    tokens = 0
    split = False

    def flush() -> None:
        nonlocal current, tokens, split
        if current:
            flags: list[str] = []
            if tokens > PARENT_MAX:
                flags.append("oversized")
            if split:
                flags.append("split")
            if not current_path:
                flags.append("no_heading")
            if tokens < PARENT_MIN:
                flags.append("short")
            parents.append((current_path, current, flags))
        current = []
        tokens = 0
        split = False

    for block in blocks:
        block_tokens = count_tokens(block.text)
        if block.kind == "heading":
            if current and tokens >= PARENT_MIN:
                flush()
                current_path = block.heading_path
            elif not current:
                current_path = block.heading_path
            current.append(block)
            tokens += block_tokens
            continue

        if current and tokens + block_tokens > PARENT_MAX and tokens >= PARENT_MIN:
            flush()
            split = True
            current_path = block.heading_path or current_path
        current.append(block)
        tokens += block_tokens

    flush()
    return parents


def _make_children(
    blocks: list[Block],
) -> list[tuple[str, list[str], str, tuple[str, ...]]]:
    units = [block for block in blocks if block.kind != "heading"]
    if not units:
        text = "\n".join(block.text for block in blocks).strip()
        heading = blocks[0].heading_path if blocks else ()
        return (
            [(text, ["short"] if count_tokens(text) < CHILD_MIN else [], "text", heading)]
            if text
            else []
        )

    children: list[tuple[str, list[str], str, tuple[str, ...]]] = []
    buffer: list[str] = []
    buffer_tokens = 0
    buffer_heading: tuple[str, ...] = ()
    overlap = ""

    def flush() -> None:
        nonlocal buffer, buffer_tokens, buffer_heading, overlap
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if overlap:
            candidate = f"{overlap}\n{text}".strip()
            if count_tokens(candidate) <= CHILD_MAX:
                text = candidate
        flags: list[str] = []
        if count_tokens(text) < CHILD_MIN:
            flags.append("short")
        if count_tokens(text) > CHILD_MAX:
            flags.append("oversized")
        children.append((text, flags, "text", buffer_heading))
        overlap = text[-max(1, int(len(text) * OVERLAP_RATIO)) :]
        buffer = []
        buffer_tokens = 0
        buffer_heading = ()

    for block in units:
        if block.kind == "table":
            flush()
            text = block.text.strip()
            if count_tokens(text) > CHILD_MAX:
                for group in _table_groups(text, CHILD_MAX):
                    flags = ["table_split"]
                    if count_tokens(group) > CHILD_MAX:
                        flags.append("oversized")
                    children.append((group, flags, "table", block.heading_path))
            else:
                children.append((text, [], "table", block.heading_path))
            overlap = ""
            continue

        if block.kind == "code":
            flush()
            text = block.text.strip()
            flags = ["oversized"] if count_tokens(text) > CHILD_MAX else []
            children.append((text, flags, block.kind, block.heading_path))
            overlap = ""
            continue

        if buffer and block.heading_path != buffer_heading:
            flush()
        if not buffer:
            buffer_heading = block.heading_path

        parts = (
            [block.text]
            if count_tokens(block.text) <= CHILD_BASE_MAX
            else _split_text(block.text, CHILD_BASE_MAX)
        )
        for part in parts:
            part_tokens = count_tokens(part)
            if buffer and buffer_tokens + part_tokens > CHILD_BASE_MAX:
                flush()
                buffer_heading = block.heading_path
            buffer.append(part)
            buffer_tokens = count_tokens("\n".join(buffer))
            if buffer_tokens >= CHILD_BASE_MAX:
                flush()
                buffer_heading = block.heading_path

    flush()

    merged: list[tuple[str, list[str], str, tuple[str, ...]]] = []
    for text, flags, kind, heading in children:
        if (
            kind == "text"
            and count_tokens(text) < 80
            and merged
            and merged[-1][2] == "text"
            and merged[-1][3] == heading
            and count_tokens(merged[-1][0] + "\n" + text) <= CHILD_MAX
        ):
            previous_text, previous_flags, previous_kind, previous_heading = merged[-1]
            merged[-1] = (
                previous_text + "\n" + text,
                previous_flags,
                previous_kind,
                previous_heading,
            )
        else:
            merged.append((text, flags, kind, heading))
    return merged


def _table_groups(text: str, max_tokens: int) -> list[str]:
    """超长表格按行组切；每组重复表头；无分隔行按 20 行/组。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    if len(lines) >= 2 and _is_table_separator(lines[1]):
        header = lines[:2]
        rows = lines[2:]
    else:
        header = []
        rows = lines

    if not header:
        return ["\n".join(rows[start : start + 20]) for start in range(0, len(rows), 20)]

    header_text = "\n".join(header)
    header_tokens = count_tokens(header_text)
    groups: list[str] = []
    current: list[str] = []
    tokens = header_tokens
    for row in rows:
        row_tokens = count_tokens(row)
        if current and tokens + row_tokens > max_tokens:
            groups.append("\n".join([*header, *current]))
            current = []
            tokens = header_tokens
        current.append(row)
        tokens += row_tokens
    if current:
        groups.append("\n".join([*header, *current]))
    return groups


def _split_text(text: str, max_tokens: int) -> list[str]:
    """按句号/换行切；单句仍超限就按字符硬切。"""
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？!?；;])\s*|\n+", text) if piece.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for piece in pieces:
        piece_tokens = count_tokens(piece)
        if current and current_tokens + piece_tokens > max_tokens:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0
        if piece_tokens > max_tokens:
            for index in range(0, len(piece), max_tokens):
                chunks.append(piece[index : index + max_tokens])
            continue
        current.append(piece)
        current_tokens += piece_tokens
    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]
