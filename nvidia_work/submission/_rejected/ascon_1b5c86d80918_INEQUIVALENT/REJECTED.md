# REJECTED — NOT a valid result

Candidate `1b5c86d80918` (arith-arch on tlul_cmd_intg_chk.v), ADP 0.9667, LEC INCONCLUSIVE.

**Functionally inequivalent.** It uses the WRONG integrity-bit slices:
`cmd_intg = tl_i[21:15]` (correct = [14:8]) and `data_intg = tl_i[14:8]` (correct = [7:1]).
An independent 100,000-vector module differential test found **7 mismatches**, including
false negatives (MISSED integrity errors) — decisive for a bus command-integrity checker.

Kept only as evidence of why formal/targeted checking matters. The valid ASCON result is the
LEC-PROVEN runner-up `b153b877f996` (ADP 0.9792) in `nvidia_work/submission/ascon`.
See NVIDIA_JULY19_CAMPAIGN_REVIEW.md.
