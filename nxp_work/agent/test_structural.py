#!/usr/bin/env python3
"""Sabotage validation for validators.structural_diff — reference must pass
clean; each single-fault mutation of the reference top must be caught with
the right typed error. Run: python3 test_structural.py"""
from pathlib import Path
import re
import sys

import validators as V

REF = (Path(__file__).resolve().parents[1] / "rtl/secure_periph_soc.v").read_text()
GEN = ["ahb_to_apb_bridge", "apb_fabric5", "apb_gpio", "apb_timer", "apb_uart",
       "apb_watchdog", "irq_aggregator", "reset_sync"]

CASES = []  # (name, mutate(text)->text, expected error substring)

# clean reference
CASES.append(("reference-clean", lambda t: t, None))

# census: drop the whole UART instance
CASES.append(("drop-uart-instance",
              lambda t: re.sub(r"apb_uart\s*#[^;]+;", "", t, flags=re.S),
              "struct-census: apb_uart instantiated 0x"))

# census: duplicate the GPIO instance
def dup_gpio(t):
    m = re.search(r"apb_gpio\s*#[^;]+;", t, flags=re.S)
    dup = m.group(0).replace("u_gpio", "u_gpio2")
    return t.replace(m.group(0), m.group(0) + "\n" + dup)
CASES.append(("duplicate-gpio-instance", dup_gpio,
              "struct-census: apb_gpio instantiated 2x"))

# dangling: disconnect a top port (pwm1 left unwired)
CASES.append(("dangling-top-port",
              lambda t: t.replace(".pwm0(pwm0), .pwm1(pwm1)", ".pwm0(pwm0)"),
              "struct-dangling: top port pwm1"))

# irq: uart_irq dropped from the aggregator concat
CASES.append(("uart-irq-unreachable",
              lambda t: t.replace("timer_irq, gpio_irq, uart_irq, 1'b0",
                                  "timer_irq, gpio_irq, 1'b0, 1'b0"),
              "struct-irq: u_uart.irq net 'uart_irq'"))

# fabric: timer's psel taken from the master bus instead of a slave select
CASES.append(("timer-psel-off-master",
              lambda t: t.replace(".psel(s2_psel)", ".psel(m_psel)"),
              "struct-fabric: u_timer.psel 'm_psel'"))

# fabric: timer and uart share s0_psel
CASES.append(("timer-uart-share-select",
              lambda t: t.replace(".psel(s2_psel)", ".psel(s0_psel)"),
              "share slave select 's0_psel'"))

# bridge: fabric master select wired to the wrong net
CASES.append(("bridge-fabric-broken",
              lambda t: t.replace(".m_psel(m_psel)", ".m_psel(m_penable)"),
              "struct-bridge:"))


def main():
    failures = 0
    for name, mutate, expect in CASES:
        ok, errs = V.structural_diff(mutate(REF), GEN)
        if expect is None:
            good = ok
            detail = "" if ok else f" unexpected: {errs}"
        else:
            good = (not ok) and any(expect in e for e in errs)
            detail = "" if good else f" wanted '{expect}', got: {errs}"
        print(f"[{'PASS' if good else 'FAIL'}] {name}{detail}")
        failures += 0 if good else 1
    print(f"structural_diff sabotage: {len(CASES)-failures}/{len(CASES)} PASS")
    return failures


if __name__ == "__main__":
    sys.exit(main())
