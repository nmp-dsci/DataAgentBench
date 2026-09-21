# yelp — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| yelp_review."user_id" | yelp_user."user_id" | 1,518 | 1.0 | 1.0 | 1.0 |
| yelp_tip."user_id" | yelp_user."user_id" | 546 | 1.0 | 1.0 | 1.0 |
| yelp_review."useful" | yelp_user."useful" | 39 | 1.0 | 1.0 | 1.0 |
| yelp_review."funny" | yelp_user."funny" | 10 | 1.0 | 1.0 | 1.0 |
| yelp_review."cool" | yelp_user."cool" | 17 | 1.0 | 1.0 | 1.0 |
| yelp_business."business_id" | yelp_checkin."business_id" | 100 | 0.9 | 0.9 | 0.9 |
| yelp_business."review_count" | yelp_user."review_count" | 49 | 0.898 | 0.898 | 0.898 |
| yelp_review."business_ref" | yelp_tip."business_ref" | 100 | 0.75 | 0.75 | 0.75 |
| yelp_review."user_id" | yelp_tip."user_id" | 1,518 | 0.0428 | 0.0428 | 0.0428 |
| yelp_review."text" | yelp_tip."text" | 1,998 | 0.0005 | 0.0005 | 0.0547 |
| yelp_business."business_id" | yelp_review."business_ref" | 100 | 0.0 | 0.0 | 1.0 |
| yelp_business."business_id" | yelp_tip."business_ref" | 100 | 0.0 | 0.0 | 0.75 |
| yelp_business."name" | yelp_user."name" | 100 | 0.0 | 0.0 | 0.0 |
| yelp_checkin."business_id" | yelp_review."business_ref" | 90 | 0.0 | 0.0 | 1.0 |
| yelp_checkin."business_id" | yelp_tip."business_ref" | 90 | 0.0 | 0.0 | 0.7889 |
| yelp_checkin."date" | yelp_review."date" | 90 | 0.0 | 0.0 | 0.0 |
| yelp_checkin."date" | yelp_tip."date" | 90 | 0.0 | 0.0 | 0.0 |
| yelp_review."date" | yelp_tip."date" | 2,000 | 0.0 | 0.0 | 0.0005 |
