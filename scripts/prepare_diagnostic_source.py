"""Prepare a local-only capacity variant without redistributing author code."""

from __future__ import annotations

import argparse
import ast
import io
import logging
import shutil
import tokenize
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CAPACITIES = (1, 3, 5)
LOGGER = logging.getLogger(__name__)


def _text_offset(lines: list[str], line_number: int, utf8_column: int) -> int:
    """Convert AST's UTF-8 column offset to a decoded string character offset."""
    prefix = lines[line_number - 1].encode("utf-8")[:utf8_column].decode("utf-8")
    return sum(len(line) for line in lines[: line_number - 1]) + len(prefix)


def _replace_capacity(source_bytes: bytes, capacity: int) -> bytes:
    """Replace only the sole top-level integer capacity literal, preserving bytes."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
    source = source_bytes.decode(encoding)
    tree = ast.parse(source)
    assignments = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(item, ast.Name) and item.id == "max_num" for item in targets):
            assignments.append((node, targets))
    if len(assignments) != 1:
        raise ValueError("Expected exactly one top-level max_num assignment")
    assignment, targets = assignments[0]
    value = assignment.value
    if (
        len(targets) != 1
        or not isinstance(targets[0], ast.Name)
        or not isinstance(value, ast.Constant)
        or type(value.value) is not int
    ):
        raise ValueError(
            "Top-level max_num must be a single integer-literal assignment"
        )
    if value.end_lineno is None or value.end_col_offset is None:
        raise ValueError("Cannot locate the max_num integer literal")
    lines = source.splitlines(keepends=True)
    start = _text_offset(lines, value.lineno, value.col_offset)
    end = _text_offset(lines, value.end_lineno, value.end_col_offset)
    return (source[:start] + str(capacity) + source[end:]).encode(encoding)


def prepare_source(source_dir: Path, output_dir: Path, capacity: int) -> Path:
    """Copy two author Python files to a new external local diagnostic directory.

    Only ``max_num`` in the main file changes; ``utils.py`` is copied verbatim.
    Maps, PDFs, archives and all other inputs are never copied. Output must be
    outside this repository and the original source directory. Existing output
    raises ``FileExistsError``; invalid paths or capacity raise ``ValueError``.
    No files or directories are overwritten or deleted, including on failure.
    """
    if type(capacity) is not int or capacity not in CAPACITIES:
        raise ValueError(f"Capacity must be one of {CAPACITIES}")
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    repository = REPOSITORY_ROOT.resolve()
    if output_dir.is_relative_to(repository):
        raise ValueError("Diagnostic author copies must stay outside the repository")
    if output_dir.is_relative_to(source_dir):
        raise ValueError("Diagnostic output must stay outside the original source")
    if output_dir.exists():
        raise FileExistsError(f"Diagnostic output already exists: {output_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(source_dir)
    main_path = source_dir / "main_sunlight_3Dgrid.py"
    utils_path = source_dir / "utils.py"
    for required in (main_path, utils_path):
        if not required.is_file():
            raise FileNotFoundError(required)
    modified_main = _replace_capacity(main_path.read_bytes(), capacity)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / main_path.name).write_bytes(modified_main)
    shutil.copyfile(utils_path, output_dir / utils_path.name)
    LOGGER.info(
        "Prepared local diagnosis: source=%s output=%s capacity=%s; map not copied",
        source_dir,
        output_dir,
        capacity,
    )
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Create an explicitly requested external capacity variant from local inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--capacity", type=int, choices=CAPACITIES, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        prepare_source(args.source_dir, args.output_dir, args.capacity)
    except (OSError, SyntaxError, UnicodeError, ValueError) as error:
        LOGGER.error("Cannot prepare diagnostic source: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
