## From the question to the statement

Before your first query, write the plan: one line for each step below, saying what the question needs at that step ("none" when it needs nothing). Explore to check each line against the data, then build the statement's CTEs in this order, and submit the plan with the statement (`plan` in `submit_answer`).

### 1 · sources — what the question names, and where each thing lives

### 2 · keys — how the rows match, and what each side needs first

### 3 · parse — what must be read out of text or JSON, and every phrasing it comes in

### 4 · filter — every condition, read literally, with its window

### 5 · metric — what is measured, at what grain, by what formula

### 6 · rank — the order, the tie-break, the limit

### 7 · shape — the columns the question names, one row or many, the mode
