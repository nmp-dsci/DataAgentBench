# bookreview — orientation summary

## 1. Shape
- Two stores, each with a single table.
- `bookreview_books_info` (store `books_database`): 200 rows, one row per book. Columns: title, subtitle, author, rating_number, features, description, price, store, categories, details, book_id.
- `bookreview_review` (store `review_database`): 1,833 rows, one row per review. Columns: rating, title, text, review_time, helpful_vote, verified_purchase, purchase_id.
- `bookreview_review` is the larger table (~9x more rows) and is the only table with a join partner (`bookreview_books_info`). All analysis crossing books and reviews goes through this one join.

## 2. Keys and joins
- Only measured join: `bookreview_books_info."title"` → `bookreview_review."title"` — raw share 0.035, normalised (trim/`#`-strip/lower-case) share 0.04, digits-only share 0.2727 (joins.md). None of these shares are usable (far below 1.0); title-to-title is **not** a reliable join key.
- hints.txt states the real link: "The fields 'book_id' in books_info and 'purchase_id' in review refer to the same book entities across different tables. While the field names are not exact matches, they can be joined using a fuzzy join approach to solve the query." No overlap numbers for `book_id`/`purchase_id` are given in joins.md — treat the exact normalisation needed as unmeasured; sample values are `bookid_1..bookid_5` (books_info) and `purchaseid_186`, `purchaseid_191`, etc. (review), suggesting a shared numeric suffix behind different prefixes ("bookid_" vs "purchaseid_"), consistent with the fuzzy-join hint, but no confirmed overlap share exists in the material.
- No other join pairs are measured in joins.md.

## 3. Literal values
- `bookreview_review.rating`: bigint, 5 distinct values, min 1, max 5 (integer scale per description.txt: "Rating given by reviewer (1.0-5.0 scale)", though stored as bigint here, not float).
- `bookreview_review.verified_purchase`: bigint, 2 distinct values, min 0, max 1 (boolean encoded as 0/1; description.txt calls it "bool").
- `bookreview_books_info.categories`: text, 97 distinct values, stored as a string representation of a list, e.g. `["Books", "Literature & Fiction", "History & Criticism"]`.
- `bookreview_review.review_time`: character varying (text, not a date type), sample format `2012-11-24 18:52:00` (no timezone shown).
- No other categorical/code columns' top values are given beyond what's shown in samples.

## 4. Text columns that need reading
- `bookreview_books_info.description`: text; hints.txt: "the 'description' … content appears to be in list or dictionary format, but they are actually stored as strings"; sample shows values like `["About the Author", "SANDRA WILDE, ..."]` or `[]`.
- `bookreview_books_info.features`: text; same list/dict-as-string caveat per hints.txt; sample shows bullet-style feature strings or `[]`.
- `bookreview_books_info.categories`: text; same list-as-string caveat; hints.txt: "For some queries, you could get needed information from 'categories' or 'details' columns in books_info."
- `bookreview_books_info.details`: text, free-form prose per row (e.g. publisher, format, page count, ISBN-10/13, all folded into one string); hints.txt flags it as a source of extractable information.
- `bookreview_books_info.author`: text, contains dict-like string for some rows (e.g. `{"avatar": ..., "name": "Peter Ackroyd", "about": [...]}`) but plain "Name (Author)" strings for others (e.g. "Sandra Wilde (Editor)") — format is inconsistent across rows per the samples.
- `bookreview_review.text`: character varying, free-text review body, may contain HTML like `<br />` (seen in sample row 1).

## 5. Conventions in the description/hints
- description.txt: "purchase_id (str): Unique identifier linking to book_id in books_info table in books_database."
- description.txt: "rating (float): Rating given by reviewer (1.0-5.0 scale)" — note actual column type in schema.md is bigint.
- description.txt: "verified_purchase (bool): Whether purchase was verified" — note actual column type in schema.md is bigint (0/1).
- hints.txt: "In books_info, the 'description', 'categories', and 'features' content appears to be in list or dictionary format, but they are actually stored as strings in the .sql file."
- hints.txt: "The fields 'book_id' in books_info and 'purchase_id' in review refer to the same book entities across different tables. While the field names are not exact matches, they can be joined using a fuzzy join approach to solve the query."
- hints.txt: "For some queries, you could get needed information from 'categories' or 'details' columns in books_info."
- No formulas (e.g. average rating, helpfulness ratio) are stated anywhere in description.txt or hints.txt.
