# Trade Journal

Every entry and exit, real or dry-run, gets an entry here in this format:

```
## YYYY-MM-DD HH:MM ET · TICKER · ENTRY|EXIT · sleeve · [DRY RUN|LIVE]
- Signal: what triggered it, with the indicator values
- Entry / Stop / Target: $x / $y / $z  (risk per share $x - $y)
- Size math: equity $E x 3% = max risk $R; $R / risk per share = N shares;
  capped by 20% position limit at M shares -> N used
- Earnings in window: yes/no
- Order: type, limit price, order id, fill
- Outcome (on exit): P&L $ and %, R-multiple, days held
- Lesson: one sentence
```

---

_No trades yet. Account unfunded; system in setup._
