# stockmarket — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| stockmarket_stocktrade_all."Date" | stockmarket_cvx."Date" | 10,887 | 1.0 | 1.0 | 1.0 |
| stockmarket_stocktrade_all."Date" | stockmarket_cmi."Date" | 11,196 | 0.9528 | 0.9887 | 0.9917 |
| stockmarket_cvx."Date" | stockmarket_cmi."Date" | 14,663 | 0.8105 | 0.8105 | 0.8105 |
| stockmarket_cvx."High" | stockmarket_cmi."High" | 5,252 | 0.2515 | 0.2515 | 0.2621 |
| stockmarket_cvx."Low" | stockmarket_cmi."Low" | 5,247 | 0.2508 | 0.2508 | 0.2622 |
| stockmarket_cvx."Close" | stockmarket_cmi."Close" | 5,328 | 0.2476 | 0.2476 | 0.2599 |
| stockmarket_cvx."Open" | stockmarket_cmi."Open" | 5,022 | 0.2451 | 0.2451 | 0.2495 |
| stockmarket_cvx."Volume" | stockmarket_cmi."Volume" | 9,667 | 0.2115 | 0.2115 | 0.2115 |
| stockmarket_stocktrade_all."High" | stockmarket_cvx."High" | 34,925 | 0.1197 | 0.1251 | 0.1207 |
| stockmarket_stocktrade_all."Volume" | stockmarket_cmi."Volume" | 31,015 | 0.1171 | 0.123 | 0.1264 |
| stockmarket_stocktrade_all."Open" | stockmarket_cvx."Open" | 32,972 | 0.1245 | 0.1222 | 0.122 |
| stockmarket_stocktrade_all."Volume" | stockmarket_cvx."Volume" | 29,507 | 0.121 | 0.1215 | 0.115 |
| stockmarket_stocktrade_all."Close" | stockmarket_cvx."Close" | 35,832 | 0.1189 | 0.1204 | 0.125 |
| stockmarket_stocktrade_all."Low" | stockmarket_cvx."Low" | 34,475 | 0.1195 | 0.1187 | 0.1228 |
| stockmarket_stocktrade_all."Open" | stockmarket_cmi."Open" | 33,040 | 0.0989 | 0.1031 | 0.0962 |
| stockmarket_stocktrade_all."Close" | stockmarket_cmi."Close" | 35,767 | 0.0941 | 0.0987 | 0.0957 |
| stockmarket_stocktrade_all."Low" | stockmarket_cmi."Low" | 34,526 | 0.0949 | 0.0942 | 0.1 |
| stockmarket_stocktrade_all."High" | stockmarket_cmi."High" | 34,838 | 0.0963 | 0.0928 | 0.106 |
| stockmarket_stocktrade_all."Adj Close" | stockmarket_cvx."Adj Close" | 141,081 | 0.0022 | 0.0034 | 0.0037 |
| stockmarket_stocktrade_all."Adj Close" | stockmarket_cmi."Adj Close" | 151,835 | 0.0001 | 0.0002 | 0.0001 |
| stockmarket_cvx."Adj Close" | stockmarket_cmi."Adj Close" | 9,763 | 0.0001 | 0.0001 | 0.0001 |
