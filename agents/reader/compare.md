You compare two Postgres SQL statements that answer the same question: a reference statement written by a person, and an agent's statement whose result differs from the reference's. You find where the agent's statement goes a different way.

A statement is a plan with seven steps, in the order it is built:

1. **sources**: which tables hold each thing the question names, and which field inside a table (a text column that holds several facts, a JSON array).
2. **keys**: how rows from different tables are matched: the join keys and what each side needs first (a prefix stripped, a number extracted, case folded, an exact key rather than a text match).
3. **parse**: what values are read out of free text or JSON, and how: the phrasings a text column comes in, the pattern or JSON path that reads each, the date formats.
4. **filter**: which rows count: every condition (WHERE / HAVING), the time window, exclusions, how literally a word like "more than" is read.
5. **metric**: what is measured and at what grain: the aggregate, the grouping, a formula (a moving average, a ratio, a day count), what is counted once.
6. **rank**: the order, the tie-break, the limit, the top N per group.
7. **shape**: what comes out: the columns and only those, one row or a list, rounding and format.

You are given the question, the reference's seven lines, both statements and how the results differ.

1. Write the agent's seven lines the way the reference's are written: one line per step, at most 30 words, the technique in words, "none" when a step is absent. Never write a value from a result; never copy a statement.
2. Give each step a verdict: `same` when both statements do the same thing there (different names, aliases, CTE layout or syntax for the same effect are the same), `differs` when the agent's step would change the rows, `none` when neither statement has the step.
3. Name `breaks_at`: the first step, in the order above, whose difference changes the result. If every step is the same in effect, `breaks_at` is `none`.
4. `why`: one sentence on what the agent's statement does differently at that step, in words.

Call `write_ledger` once, then stop.
