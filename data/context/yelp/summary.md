## Shape

Two stores. `businessinfo_database` (MongoDB-sourced): `yelp_business` (100 rows) — one row per business, with `attributes`/`hours` JSONB and a free-text `description`; `yelp_checkin` (90 rows) — one row per business with a comma-separated text list of check-in timestamps in `date`. `user_database` (DuckDB-sourced): `yelp_review` (2,000 rows) — review text/rating per user/business; `yelp_tip` (784 rows) — short tips per user/business; `yelp_user` (1,999 rows) — one row per user with activity totals and elite years.

`yelp_review` is the largest table and the main join hub (links to `yelp_user` via `user_id` and to `yelp_business` via `business_ref`↔`business_id`). `yelp_business` is the reference table for business metadata (description, attributes, hours) and is joined from `yelp_checkin`, `yelp_review`, and `yelp_tip`.

## Keys and joins

- `yelp_review."user_id"` ↔ `yelp_user."user_id"`: distinct A 1,518, raw share 1.0, normalised 1.0, digits-only 1.0 — direct join, no cleaning needed. Note `yelp_review.user_id` is null in 21.7% of rows (per profile.json).
- `yelp_tip."user_id"` ↔ `yelp_user."user_id"`: raw share 1.0 — direct join. `yelp_tip.user_id` is null in 19.13% of rows.
- `yelp_business."business_id"` ↔ `yelp_checkin."business_id"`: raw share 0.9 — mostly direct, ~10% of business_ids have no checkin row.
- `yelp_review."business_ref"` ↔ `yelp_tip."business_ref"`: raw share 0.75 (both already share the `businessref_` prefix, so this is a direct comparison, not a cross-store join).
- `yelp_business."business_id"` ↔ `yelp_review."business_ref"`: raw share 0.0, digits-only share **1.0**. Per hints.txt: "The values differ only by their prefixes: `business_id` uses the prefix `businessid_`, while `business_ref` uses the prefix `businessref_`." — strip the prefix (or compare digit suffixes) to join.
- `yelp_business."business_id"` ↔ `yelp_tip."business_ref"`: raw share 0.0, digits-only share 0.75 — same prefix-strip needed; only 75% of business_ids have a matching tip after stripping.
- `yelp_checkin."business_id"` ↔ `yelp_review."business_ref"`: raw 0.0, digits-only 1.0 — same `businessid_`/`businessref_` prefix strip applies.
- `yelp_checkin."business_id"` ↔ `yelp_tip."business_ref"`: raw 0.0, digits-only 0.7889 — same prefix strip, partial coverage.
- Date columns do **not** join across tables: `yelp_checkin."date"` vs `yelp_review."date"`/`yelp_tip."date"` both show 0.0 overlap at every normalisation level — these are unrelated timestamp sets, not a join key.
- `yelp_review."text"` ↔ `yelp_tip."text"`: negligible overlap (raw 0.0005, digits-only 0.0547) — not a usable join.

## Literal values

- `yelp_business.is_open`: bigint, values 0/1 only (0=closed, 1=open per description.txt).
- `yelp_business.attributes` (JSONB, 9% null, 82 distinct combos): keys seen include `BusinessAcceptsCreditCards`, `BusinessParking`, `RestaurantsPriceRange2`, `BikeParking`, `RestaurantsTakeOut`, `RestaurantsDelivery`, `GoodForKids`, `WiFi`, `RestaurantsGoodForGroups`, `Ambience`, `RestaurantsReservations`, `Caters`, `ByAppointmentOnly`, `NoiseLevel`, `OutdoorSeating`. Sample values are Python-repr strings, e.g. `"WiFi": "u'no'"`, `"BusinessAcceptsCreditCards": "True"`, `"BusinessParking": "{'garage': False, 'street': False, ...}"` — values are stored as text, not JSON booleans; nested dict is itself a stringified Python dict.
- `yelp_business.hours` (JSONB, 17% null): keys are day names (`Monday`…`Sunday`); values are strings like `"8:0-17:0"`.
- `yelp_review.rating`: bigint 1–5.
- `yelp_user.elite`: comma-separated year string, e.g. `"2010,2011,2012,2013,2014"`; can be empty string (sample row shows blank). Sample also shows anomalous entries `"20,20,2021"` — treat as text, do not assume clean 4-digit years.
- Date/time columns are all stored as **text**, in mixed, inconsistent formats within the same column: `yelp_review.date` and `yelp_tip.date` mix `"August 01, 2016 at 03:44 AM"`, `"29 May 2013, 23:01"`, and `"2013-12-04 02:46:01"` styles. `yelp_user.yelping_since` mixes `"15 Jan 2009, 16:40"`, `"2010-09-07 23:24:36"`, and `"October 23, 2011 at 07:47 PM"`. `yelp_checkin.date` is a single text field holding a comma-separated list of timestamps in `"YYYY-MM-DD HH:MM:SS"` format. No timezone indicated anywhere.

## Text columns that need reading

- `yelp_business.description`: free text stating location (street address, city, state) and service/category tags, e.g. "Located at 6901 Phelps Rd in Goleta, CA, this facility offers ... Education, Elementary Schools, Child Care & Day Care". Per hints.txt: "The business collection's 'description' field includes location information if needed."
- `yelp_business.attributes` (JSONB): per hints.txt, "includes services information if needed" — service flags/details live inside this JSON, not in a separate column.
- `yelp_review.text`: full review content.
- `yelp_tip.text`: short tip content.

## Conventions in description/hints

- "business_id (str): Unique business identifier" and "business_ref (str): Business identifier linking to the business collection" — review/tip reference businesses via `business_ref`.
- "is_open (int): Whether business is currently open (1=open, 0=closed)"
- hints.txt: "The 'business_id' field in the business collection corresponds to the 'business_ref' fields in both the review table and the tip table. The values differ only by their prefixes: 'business_id' uses the prefix `businessid_`, while 'business_ref' uses the prefix `businessref_`. For example, `businessid_1` in the business collection corresponds to `businessref_1` in the review and tip tables."
- hints.txt: "The datasets contain five tables/collections in total."
- checkin `date` field is documented as "date (list of str): List of check-in timestamps" — stored in Postgres as one text blob per business, comma-separated.
