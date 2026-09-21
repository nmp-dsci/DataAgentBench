"""The load path without a server: naming, the pg_dump rewrite and the stream parser, the manifest check.

A live Postgres is exercised by `make data` (and `tests/test_roles.py` when
DAB_TEST_PG=1); these tests pin the pure parts that decide what lands where.
"""

from __future__ import annotations

import io
from pathlib import Path

from dab_bench.data import download
from dab_bench.data.load import _statements, rewrite_statement
from dab_bench.data.stores import Store, load_stores, pg_table, qualified

DUMP = """--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SELECT pg_catalog.set_config('search_path', '', false);

CREATE TABLE public.books_info (
    "ISBN" text,
    title text
);


ALTER TABLE public.books_info OWNER TO postgres;

CREATE INDEX idx_title ON public.books_info USING btree (title);

COPY public.books_info ("ISBN", title) FROM stdin;
1\tA public.book about SQL
2\t\\N
\\.

CREATE TABLE public."MixedCase" (id integer);
"""


def test_pg_table_folds_to_identifier() -> None:
    assert pg_table("bookreview", "books_info") == "bookreview_books_info"
    assert pg_table("crmarenapro", "Sales-Pipeline") == "crmarenapro_sales_pipeline"
    assert qualified("yelp", "business") == 'dataagentbench."yelp_business"'


def test_rewrite_points_public_at_the_schema_and_drops_owner_lines() -> None:
    assert (
        rewrite_statement("ALTER TABLE public.books_info OWNER TO postgres;", "bookreview") is None
    )
    assert rewrite_statement("SET transaction_timeout = 0;", "bookreview") is None
    assert (
        rewrite_statement("CREATE TABLE public.books_info (\n title text\n);", "bookreview")
        == 'CREATE TABLE dataagentbench."bookreview_books_info" (\n title text\n);'
    )
    assert (
        rewrite_statement('CREATE TABLE public."MixedCase" (id integer);', "bookreview")
        == 'CREATE TABLE dataagentbench."bookreview_mixedcase" (id integer);'
    )
    # index names are prefixed too: two datasets' dumps may carry the same index name
    assert rewrite_statement(
        "CREATE INDEX idx_title ON public.books_info USING btree (title);", "bookreview"
    ) == (
        'CREATE INDEX "bookreview_idx_title" ON dataagentbench."bookreview_books_info" '
        "USING btree (title);"
    )


def test_statement_stream_separates_copy_blocks_and_keeps_data_verbatim() -> None:
    lines = iter(io.StringIO(DUMP).readlines())
    seen: list[tuple[str, list[str] | None]] = []
    for stmt, copy in _statements(lines):
        seen.append((stmt.split("\n")[0], list(copy) if copy is not None else None))
    heads = [h for h, _ in seen]
    assert heads[0] == "SET statement_timeout = 0;"
    assert "CREATE TABLE public.books_info (" in heads
    copy_rows = next(c for h, c in seen if h.startswith("COPY"))
    # the data line containing `public.` is never rewritten: it is data, not DDL
    assert copy_rows == ["1\tA public.book about SQL\n", "2\t\\N\n"]
    assert heads[-1] == 'CREATE TABLE public."MixedCase" (id integer);'


def test_index_lists_every_released_store_with_its_target_names() -> None:
    stores = load_stores()
    datasets = {s.dataset for s in stores}
    assert len(datasets) == 12
    engines = {s.engine for s in stores}
    assert engines == {"sqlite", "duckdb", "postgres", "mongo"}
    mongo = [s for s in stores if s.engine == "mongo"]
    assert all(s.dump_folder and s.db_name for s in mongo)
    files = [s for s in stores if s.engine != "mongo"]
    assert all(s.file for s in files)
    # every file store is either in the HF manifest (sha256 known) or a real file in the git tree
    off_manifest = [s for s in files if not s.in_manifest]
    assert [f"{s.dataset}/{s.name}" for s in off_manifest] == ["music_brainz_20k/sales_database"]
    assert all(s.sha256 for s in files if s.in_manifest)


def test_download_matches_needs_size_and_digest(tmp_path: Path) -> None:
    p = tmp_path / "x.db"
    p.write_bytes(b"hello")
    digest = download.sha256_of(p)
    assert download.matches(p, digest, 5)
    assert not download.matches(p, digest, 4)  # an LFS pointer stub has the wrong size
    assert not download.matches(p, "0" * 64, 5)
    assert not download.matches(tmp_path / "missing.db", digest, 5)
    s = Store("d", "query_d", "s", "sqlite", "x.db", None, None, 5, digest, True)
    assert download.needed([s]) == [s]  # the store's path is under data/upstream, not tmp
