# googlelocal — summary

## Shape
- Two stores: `review_database` (SQLite-origin) and `business_database` (PostgreSQL-origin). In this Postgres instance, both are tables under schema `dataagentbench`, named `googlelocal_<table>`.
- `googlelocal_business_description` — 79 rows, source table `business_description`. One row per business: name, gmap_id, free-text description, num_of_reviews, hours, MISC, state.
- `googlelocal_review` — 2,000 rows, source table `review`. One row per review: reviewer name, time, rating (1–5), text, gmap_id.
- `googlelocal_review` is the largest table (2,000 rows vs 79) and the only join partner for `googlelocal_business_description`; every query that combines business metadata with review content goes through this join.

## Keys and joins
- Join: `googlelocal_business_description."gmap_id"` = `googlelocal_review."gmap_id"`. From joins.md: distinct A = 79, raw share = 1.0, normalised share = 1.0, digits-only share = 1.0. This is a clean, exact-match key — no prefix stripping, trimming, or case-folding needed.
- Do NOT join on `name`: joins.md shows `googlelocal_business_description."name"` → `googlelocal_review."name"` raw share = 0.0127, normalised share = 0.0127, digits-only share = 0.1667 — these are different name spaces (business name vs. reviewer name) and are not a usable join key.

## Literal values
- `googlelocal_business_description.state` (27 distinct values) holds live/derived Google Maps status strings, not a clean enum. Top values from the profile include exact strings: `"Open ⋅ Closes 5PM"` (18), `"Closed ⋅ Opens 10AM"` (5), `"Open ⋅ Closes 9:30PM"` (4), `"Open now"` (4), `"Open ⋅ Closes 6PM"` (3), `"Open ⋅ Closes 4PM"` (3), `"Permanently closed"` (3), `"Open ⋅ Closes 7PM"` (3), `"Open ⋅ Closes 8PM"` (3), `"Closed ⋅ Opens 9AM"` (3). Any exact-match filter must reproduce these spellings including the `⋅` character.
- `googlelocal_business_description.MISC` is JSON-shaped text (see below) with top-value examples such as `{"Accessibility": ["Wheelchair accessible entrance"]}` (21 occurrences) — category keys observed in samples/top values include "Accessibility", "Planning", "Offerings", "Amenities", "Service options", "Health & safety", "Payments".
- `googlelocal_review.rating` is bigint, 1–5 scale (min "1", max "5" per profile), 5 distinct values.
- Date/time columns are text, not native date/timestamp types, and are inconsistently formatted:
  - `googlelocal_review.time` (character varying) mixes at least two formats observed in samples: `"September 03, 2020 at 04:15 PM"` and `"2021-04-12 17:07:52"`. No timezone indicated in either format.
  - `googlelocal_business_description.hours` is text holding a JSON-array-of-arrays-like string, e.g. `[["Thursday","6:30AM–6PM"], ...]` — day name plus hour-range string, no explicit timezone.

## Text columns that need reading
- `googlelocal_business_description.description` (text, 79 distinct, 0% null) — free-text business description; per hints.txt, "You can get needed information from the 'description' column in business_database." Sample text embeds city/state/zip (e.g., "Los Angeles, CA 90023") and business category language inline.
- `googlelocal_business_description.MISC` (text, 20.25% null, 36 distinct) — stores a JSON-dict-shaped string of category → list-of-attributes (e.g. Accessibility, Offerings, Amenities, Payments); must be parsed/matched as text or via `->>`-style JSON access rather than filtered as a flat column.
- `googlelocal_business_description.hours` (text, 16.46% null, 54 distinct) — JSON-array-shaped string of [day, hour-range] pairs; needs parsing to extract per-day hours.
- `googlelocal_review.text` (character varying, 1,982 distinct) — free-text review body; per samples, may also embed location phrases (e.g., "Los Angeles, CA 90023") inside quoted reviewer commentary.

## Conventions in the description/hints
- description.txt: "review_database ... contains review information from Google Maps (reviewer name, ratings, text, etc.) collected up to September 2021 in the United States."
- description.txt: "business_database ... contains business metadata from Google Maps (business name, description, hours, etc.) collected up to September 2021 in the United States."
- description.txt: gmap_id "Google Maps business identifier (links to review_database)" (stated on the business_database side) / "(str): Google Maps business identifier" (review_database side).
- description.txt: "state (str): Business operating status (e.g., open, closed, temporarily closed)" — this is the field's stated meaning, though observed values in profile.json are richer strings like "Open ⋅ Closes 5PM" rather than a clean enum.
- hints.txt: "The two databases can be joined using the gmap_id field to combine review information with business metadata."
- hints.txt: "You can get needed information from the 'description' column in business_database."
