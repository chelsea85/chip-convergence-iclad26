Archived 2026-07-24 per Codex banking review (NVIDIA_BANKING_REVIEW_ASYNC_FIFO_PRIM_2026-07-24.md):
this candidate removes the registered Gray pointer outputs (8 FFs) and computes gray(bin)
combinationally at the clock-domain crossing. The combinational encoder can GLITCH during multi-bit
binary transitions; the receiving domain samples asynchronously -> intermittent pointer corruption.
RTL LEC and zero-delay simulation are structurally incapable of representing this failure class —
all recorded PASS/PROVEN verdicts are correct in their model and insufficient for CDC safety.
NOT cleared for hardware-safe submission. Submission reverted to pristine baseline (registered Gray).
