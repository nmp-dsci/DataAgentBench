## Entity resolution across `music_brainz_20k_tracks`
- Each real-world track appears once per `source_id` (1-5): ~5 duplicate rows per song, each wrapping title/artist differently. For a question naming one song/artist, find ALL matching `track_id`s across every source and aggregate sales over that union, not just one row — using one resolved track_id undercounts revenue/units.
- Per-source wrapping:
  - source_id=1: `title` = "Real Title (Album Name)"; `artist`/`album` hold real values directly.
  - source_id=2: `title` = "Artist - Real Title"; `artist` column is NULL.
  - source_id=3: `title` = "Real Title - Album Name"; `album` column is NULL.
  - source_id=4: `title` = "NNN-Real Title" (leading digit prefix + separator to strip).
  - source_id=5: `title`/`artist`/`album`/`year` may have minor typos/spacing vs. other sources.
- To match a named song/artist across sources: extract real title/artist per above, then normalize (lower-case, strip accents, drop non-alphanumeric chars) before comparing — raw equality only matches one source and undercounts aggregates.
- `year` is free text with inconsistent formats; use regex, not numeric equality.

## `music_brainz_20k_sales`
- Resolve all duplicate track_ids for the named entity first, then join to sales; a single track_id join is usually incomplete.
