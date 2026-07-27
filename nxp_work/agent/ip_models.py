#!/usr/bin/env python3
"""Cycle-stepped reference models for the 12 rtl_gen_lib ip_types NOT used by
the easy SoC (medium/hard vocabulary): sync_fifo, async_fifo, sram_sp,
sram_dp, cdc_sync, perf_counter, axi_lite_sram, dma_engine,
axi_lite_crossbar, tilelink_router, tilelink_ni, aes128.

Same discipline as ref_models.py: transcribed statement-for-statement from
the library's generated RTL with Verilog NBA semantics (conditions evaluate
pre-edge state, textual order, last write wins), library quirks preserved —
the AES core IGNORES its `encrypt` input (encrypt-only; inv_sbox unused) and
the TileLink router computes its XY decision but only DELIVERS local-destined
packets (non-local traffic is granted ready and consumed; inter-router
forwarding is a top-level concern), with D-responses broadcast to the
current arbitration winner.

Uniform interface, validated by test_ip_models.py lockstep against the
generated RTL:
  PORTS[ip]   ordered (name, width, dir) — harness contract; multi-clock
              IPs run all clocks from one base clock in the harness
  m.step(ins) one posedge with the given input dict
  m.outputs(ins) -> dict  output values as sampled just after that posedge
              (new state + held inputs; combinational outs use `ins`)
"""
from __future__ import annotations

M32 = 0xFFFFFFFF


def _mask(w): return (1 << w) - 1


# ── sync_fifo ─────────────────────────────────────────────────────────────────
class SyncFifo:
    PORTS = [("wr_en", 1, "i"), ("rd_en", 1, "i"), ("din", 32, "i"),
             ("dout", 32, "o"), ("full", 1, "o"), ("empty", 1, "o"),
             ("almost_full", 1, "o"), ("almost_empty", 1, "o"),
             ("count", 5, "o")]
    CLKS = [("clk", "rst_n")]

    def __init__(self, depth=16, data_width=32, af_thr=None, ae_thr=None):
        self.depth = depth
        self.abits = max(1, (depth - 1).bit_length())
        self.pmask = _mask(self.abits + 1)
        self.af = af_thr if af_thr is not None else depth - 2
        self.ae = ae_thr if ae_thr is not None else 2
        self.mem = {}
        self.wp = self.rp = 0
        self.dout_r = 0

    def _count(self): return (self.wp - self.rp) & self.pmask

    def step(self, ins):
        full = self._count() == self.depth
        empty = self._count() == 0
        if ins["wr_en"] and not full:
            self.mem[self.wp & _mask(self.abits)] = ins["din"]
            self.wp = (self.wp + 1) & self.pmask
        if ins["rd_en"] and not empty:
            self.dout_r = self.mem.get(self.rp & _mask(self.abits), 0)
            self.rp = (self.rp + 1) & self.pmask

    def outputs(self, ins):
        c = self._count()
        return dict(dout=self.dout_r, full=int(c == self.depth),
                    empty=int(c == 0), almost_full=int(c >= self.af),
                    almost_empty=int(c <= self.ae), count=c)


# ── async_fifo (harness drives both clocks from the same base clock) ──────────
def _b2g(b): return b ^ (b >> 1)


class AsyncFifo:
    PORTS = [("wr_en", 1, "i"), ("din", 32, "i"), ("full", 1, "o"),
             ("rd_en", 1, "i"), ("dout", 32, "o"), ("empty", 1, "o")]
    CLKS = [("wr_clk", "wr_rst_n"), ("rd_clk", "rd_rst_n")]

    def __init__(self, depth=16, data_width=32):
        self.abits = max(1, (depth - 1).bit_length())
        self.pb = self.abits + 1
        self.mem = {}
        self.wr_bin = self.wr_gray = self.rd_bin = self.rd_gray = 0
        self.rdg1 = self.rdg2 = self.wrg1 = self.wrg2 = 0

    def _full(self):
        top2 = _mask(2) << (self.pb - 2)
        return self.wr_gray == ((~self.rdg2 & top2) | (self.rdg2 & _mask(self.pb - 2)))

    def _empty(self): return self.rd_gray == self.wrg2

    def step(self, ins):
        o = dict(self.__dict__)
        full, empty = self._full(), self._empty()
        if ins["wr_en"] and not full:
            self.mem[o["wr_bin"] & _mask(self.abits)] = ins["din"]
            self.wr_bin = (o["wr_bin"] + 1) & _mask(self.pb)
            self.wr_gray = _b2g(self.wr_bin)
        self.rdg1, self.rdg2 = o["rd_gray"], o["rdg1"]
        if ins["rd_en"] and not empty:
            self.rd_bin = (o["rd_bin"] + 1) & _mask(self.pb)
            self.rd_gray = _b2g(self.rd_bin)
        self.wrg1, self.wrg2 = o["wr_gray"], o["wrg1"]

    def outputs(self, ins):
        return dict(full=int(self._full()), empty=int(self._empty()),
                    dout=self.mem.get(self.rd_bin & _mask(self.abits), 0))


# ── sram_sp / sram_dp ─────────────────────────────────────────────────────────
class SramSp:
    PORTS = [("ce", 1, "i"), ("we", 1, "i"), ("be", 4, "i"),
             ("addr", 8, "i"), ("din", 32, "i"), ("dout", 32, "o")]
    CLKS = [("clk", None)]

    def __init__(self, depth=256, data_width=32):
        self.amask = _mask(max(1, (depth - 1).bit_length()))
        self.mem = {}
        self.dout = 0

    def step(self, ins):
        if ins["ce"]:
            a = ins["addr"] & self.amask
            old = self.mem.get(a, 0)
            if ins["we"]:
                v = old
                for bi in range(4):
                    if ins["be"] >> bi & 1:
                        v = (v & ~(0xFF << bi * 8)) | (ins["din"] & (0xFF << bi * 8))
                self.mem[a] = v
            self.dout = old                        # NBA: read pre-write value

    def outputs(self, ins):
        return dict(dout=self.dout)


class SramDp:
    PORTS = [("wr_en", 1, "i"), ("wr_be", 4, "i"), ("wr_addr", 8, "i"),
             ("wr_din", 32, "i"), ("rd_en", 1, "i"), ("rd_addr", 8, "i"),
             ("rd_dout", 32, "o")]
    CLKS = [("wr_clk", None), ("rd_clk", None)]

    def __init__(self, depth=256, data_width=32):
        self.amask = _mask(max(1, (depth - 1).bit_length()))
        self.mem = {}
        self.rd_dout = 0

    def step(self, ins):
        old_rd = self.mem.get(ins["rd_addr"] & self.amask, 0)
        if ins["wr_en"]:
            a = ins["wr_addr"] & self.amask
            v = self.mem.get(a, 0)
            for bi in range(4):
                if ins["wr_be"] >> bi & 1:
                    v = (v & ~(0xFF << bi * 8)) | (ins["wr_din"] & (0xFF << bi * 8))
            self.mem[a] = v
        if ins["rd_en"]:
            self.rd_dout = old_rd                  # NBA: pre-write value

    def outputs(self, ins):
        return dict(rd_dout=self.rd_dout)


# ── cdc_sync ──────────────────────────────────────────────────────────────────
class CdcSync:
    PORTS = [("src_data", 4, "i"), ("dst_data", 4, "o")]
    CLKS = [("dst_clk", "dst_rst_n")]

    def __init__(self, data_width=4, stages=2):
        self.w = data_width
        self.ff1 = self.ff2 = 0

    def step(self, ins):
        self.ff2, self.ff1 = self.ff1, ins["src_data"] & _mask(self.w)

    def outputs(self, ins):
        return dict(dst_data=self.ff2)


# ── perf_counter ──────────────────────────────────────────────────────────────
class PerfCounter:
    PORTS = [("event_0", 1, "i"), ("event_1", 1, "i"), ("event_2", 1, "i"),
             ("event_3", 1, "i"), ("psel", 1, "i"), ("penable", 1, "i"),
             ("pwrite", 1, "i"), ("paddr", 12, "i"), ("pwdata", 32, "i"),
             ("prdata", 32, "o"), ("pready", 1, "o"), ("pslverr", 1, "o")]
    CLKS = [("pclk", "presetn")]

    def __init__(self, channels=4, counter_width=32):
        self.ch = channels
        self.cnt = [0] * channels

    def step(self, ins):
        nxt = [(c + 1) & M32 if ins[f"event_{i}"] else c
               for i, c in enumerate(self.cnt)]
        if ins["psel"] and ins["penable"] and ins["pwrite"] and ins["paddr"] == 0:
            nxt = [0] * self.ch                    # clear-all wins (textual last)
        self.cnt = nxt

    def outputs(self, ins):
        a = ins["paddr"]
        prdata = self.cnt[a // 4] if a % 4 == 0 and a // 4 < self.ch else 0xDEADBEEF
        return dict(prdata=prdata, pready=1, pslverr=0)


# ── axi_lite_sram ─────────────────────────────────────────────────────────────
class AxiLiteSram:
    PORTS = [("awaddr", 32, "i"), ("awvalid", 1, "i"), ("awready", 1, "o"),
             ("wdata", 32, "i"), ("wstrb", 4, "i"), ("wvalid", 1, "i"),
             ("wready", 1, "o"), ("bresp", 2, "o"), ("bvalid", 1, "o"),
             ("bready", 1, "i"), ("araddr", 32, "i"), ("arvalid", 1, "i"),
             ("arready", 1, "o"), ("rdata", 32, "o"), ("rresp", 2, "o"),
             ("rvalid", 1, "o"), ("rready", 1, "i")]
    CLKS = [("aclk", "aresetn")]

    def __init__(self, depth=256, data_width=32, addr_width=32):
        self.amask = _mask(max(1, (depth - 1).bit_length()))
        self.mem = {}
        self.wr_addr_r = 0
        self.pending_w = 0
        self.awready = self.wready = self.bvalid = 0
        self.bresp = 0
        self.arready = self.rvalid = self.rdata = self.rresp = 0

    def step(self, ins):
        o = dict(self.__dict__)
        # write path
        self.awready = int(not o["pending_w"] and ins["awvalid"] and not o["awready"])
        if ins["awvalid"] and o["awready"]:
            self.wr_addr_r = ins["awaddr"] & self.amask
            self.pending_w = 1
        self.wready = int(o["pending_w"] and ins["wvalid"] and not o["wready"])
        if o["pending_w"] and ins["wvalid"] and o["wready"]:
            a = o["wr_addr_r"]
            v = self.mem.get(a, 0)
            for bi in range(4):
                if ins["wstrb"] >> bi & 1:
                    v = (v & ~(0xFF << bi * 8)) | (ins["wdata"] & (0xFF << bi * 8))
            self.mem[a] = v
            self.pending_w = 0                     # wins over the set above
            self.bvalid, self.bresp = 1, 0
        if o["bvalid"] and ins["bready"]:
            self.bvalid = 0
        # read path (separate always block — same snapshot)
        self.arready = int(ins["arvalid"] and not o["arready"] and not o["rvalid"])
        if ins["arvalid"] and o["arready"]:
            self.rdata = self.mem.get(ins["araddr"] & self.amask, 0)
            self.rresp, self.rvalid = 0, 1
        if o["rvalid"] and ins["rready"]:
            self.rvalid = 0

    def outputs(self, ins):
        return dict(awready=self.awready, wready=self.wready,
                    bresp=self.bresp, bvalid=self.bvalid,
                    arready=self.arready, rdata=self.rdata,
                    rresp=self.rresp, rvalid=self.rvalid)


# ── dma_engine ────────────────────────────────────────────────────────────────
class DmaEngine:
    S_IDLE, S_RD_ADDR, S_RD_DATA, S_WR_ADDR, S_WR_DATA, S_WR_RESP, S_DONE = range(7)
    PORTS = [("cfg_awaddr", 12, "i"), ("cfg_awvalid", 1, "i"), ("cfg_awready", 1, "o"),
             ("cfg_wdata", 32, "i"), ("cfg_wstrb", 4, "i"), ("cfg_wvalid", 1, "i"),
             ("cfg_wready", 1, "o"), ("cfg_bresp", 2, "o"), ("cfg_bvalid", 1, "o"),
             ("cfg_bready", 1, "i"), ("cfg_araddr", 12, "i"), ("cfg_arvalid", 1, "i"),
             ("cfg_arready", 1, "o"), ("cfg_rdata", 32, "o"), ("cfg_rresp", 2, "o"),
             ("cfg_rvalid", 1, "o"), ("cfg_rready", 1, "i"),
             ("m_awaddr", 32, "o"), ("m_awvalid", 1, "o"), ("m_awready", 1, "i"),
             ("m_wdata", 32, "o"), ("m_wstrb", 4, "o"), ("m_wvalid", 1, "o"),
             ("m_wready", 1, "i"), ("m_bresp", 2, "i"), ("m_bvalid", 1, "i"),
             ("m_bready", 1, "o"), ("m_araddr", 32, "o"), ("m_arvalid", 1, "o"),
             ("m_arready", 1, "i"), ("m_rdata", 32, "i"), ("m_rresp", 2, "i"),
             ("m_rvalid", 1, "i"), ("m_rready", 1, "o"), ("dma_irq", 1, "o")]
    CLKS = [("aclk", "aresetn")]

    def __init__(self, burst_len=4, data_width=32, addr_width=32):
        self.r_src = self.r_dst = self.r_len = self.r_ctrl = 0
        self.r_stat = self.r_irqstat = 0
        self.st = self.S_IDLE
        self.cur_src = self.cur_dst = self.remaining = self.rd_buf = 0

    def step(self, ins):
        o = dict(self.__dict__)
        if ins["cfg_awvalid"] and ins["cfg_wvalid"]:
            a, d = ins["cfg_awaddr"], ins["cfg_wdata"]
            if a == 0x000: self.r_src = d
            elif a == 0x004: self.r_dst = d
            elif a == 0x008: self.r_len = d
            elif a == 0x00C: self.r_ctrl = d
            elif a == 0x014: self.r_irqstat = o["r_irqstat"] & ~d
        if o["st"] == self.S_IDLE:
            self.r_stat = 0
            if o["r_ctrl"] & 1:
                self.cur_src, self.cur_dst = o["r_src"], o["r_dst"]
                self.remaining = o["r_len"]
                self.r_stat = 1
                self.st = self.S_RD_ADDR
                self.r_ctrl = self.r_ctrl & ~1     # bit clear wins over cfg write
        elif o["st"] == self.S_RD_ADDR:
            if ins["m_arready"]: self.st = self.S_RD_DATA
        elif o["st"] == self.S_RD_DATA:
            if ins["m_rvalid"]:
                self.rd_buf, self.st = ins["m_rdata"], self.S_WR_ADDR
        elif o["st"] == self.S_WR_ADDR:
            if ins["m_awready"]: self.st = self.S_WR_DATA
        elif o["st"] == self.S_WR_DATA:
            if ins["m_wready"]: self.st = self.S_WR_RESP
        elif o["st"] == self.S_WR_RESP:
            if ins["m_bvalid"]:
                self.cur_src = (o["cur_src"] + 4) & M32
                self.cur_dst = (o["cur_dst"] + 4) & M32
                self.remaining = (o["remaining"] - 4) & M32
                self.st = self.S_DONE if o["remaining"] <= 4 else self.S_RD_ADDR
        elif o["st"] == self.S_DONE:
            self.r_stat, self.r_irqstat, self.st = 2, 1, self.S_IDLE

    def outputs(self, ins):
        rd = {0x000: self.r_src, 0x004: self.r_dst, 0x008: self.r_len,
              0x00C: self.r_ctrl, 0x010: self.r_stat, 0x014: self.r_irqstat
              }.get(ins["cfg_araddr"], 0xDEADBEEF)
        return dict(cfg_awready=1, cfg_wready=1, cfg_bresp=0, cfg_bvalid=1,
                    cfg_arready=1, cfg_rdata=rd, cfg_rresp=0, cfg_rvalid=1,
                    m_awaddr=self.cur_dst, m_awvalid=int(self.st == self.S_WR_ADDR),
                    m_wdata=self.rd_buf, m_wstrb=0xF,
                    m_wvalid=int(self.st == self.S_WR_DATA),
                    m_bready=int(self.st == self.S_WR_RESP),
                    m_araddr=self.cur_src, m_arvalid=int(self.st == self.S_RD_ADDR),
                    m_rready=int(self.st == self.S_RD_DATA),
                    dma_irq=int(bool(self.r_irqstat & 1 and self.r_ctrl >> 1 & 1)))


# ── axi_lite_crossbar (2M x 3S, fixed 64KB windows) ───────────────────────────
class AxiLiteXbar:
    PORTS = ([(f"m{m}_{p}", w, d) for m in (0, 1) for p, w, d in
              [("awaddr", 32, "i"), ("awvalid", 1, "i"), ("awready", 1, "o"),
               ("wdata", 32, "i"), ("wstrb", 4, "i"), ("wvalid", 1, "i"),
               ("wready", 1, "o"), ("bresp", 2, "o"), ("bvalid", 1, "o"),
               ("bready", 1, "i"), ("araddr", 32, "i"), ("arvalid", 1, "i"),
               ("arready", 1, "o"), ("rdata", 32, "o"), ("rresp", 2, "o"),
               ("rvalid", 1, "o"), ("rready", 1, "i")]] +
             [(f"s{s}_{p}", w, d) for s in (0, 1, 2) for p, w, d in
              [("awaddr", 32, "o"), ("awvalid", 1, "o"), ("awready", 1, "i"),
               ("wdata", 32, "o"), ("wstrb", 4, "o"), ("wvalid", 1, "o"),
               ("wready", 1, "i"), ("bresp", 2, "i"), ("bvalid", 1, "i"),
               ("bready", 1, "o"), ("araddr", 32, "o"), ("arvalid", 1, "o"),
               ("arready", 1, "i"), ("rdata", 32, "i"), ("rresp", 2, "i"),
               ("rvalid", 1, "i"), ("rready", 1, "o")]])
    CLKS = [("aclk", "aresetn")]

    def __init__(self, data_width=32, addr_width=32):
        self.rr = self.rr_rd = 0

    @staticmethod
    def _hit(s, a):
        return int((a & 0xFFFF0000) == {0: 0x00000000, 1: 0x00010000,
                                        2: 0x00020000}[s])

    def _comb(self, i, rr, rr_rd):
        o = {}
        # write side
        m0w = i["m0_awvalid"] and (not i["m1_awvalid"] or not rr)
        m1w = i["m1_awvalid"] and (not i["m0_awvalid"] or rr)
        waddr = i["m0_awaddr"] if m0w else i["m1_awaddr"]
        ws = [self._hit(s, waddr) for s in range(3)]
        anyw = m0w or m1w
        wdata = i["m0_wdata"] if m0w else i["m1_wdata"]
        wstrb = i["m0_wstrb"] if m0w else i["m1_wstrb"]
        wvalid = i["m0_wvalid"] if m0w else i["m1_wvalid"]
        for s in range(3):
            o[f"s{s}_awaddr"] = waddr
            o[f"s{s}_awvalid"] = int(anyw and ws[s])
            o[f"s{s}_wdata"] = wdata
            o[f"s{s}_wstrb"] = wstrb
            o[f"s{s}_wvalid"] = int(bool(wvalid) and ws[s])
            o[f"s{s}_bready"] = (i["m0_bready"] if (ws[s] and m0w) else
                                 i["m1_bready"] if (ws[s] and m1w) else 0)
        sw_rdy = any(ws[s] and i[f"s{s}_awready"] for s in range(3))
        o["m0_awready"] = int(bool(m0w) and sw_rdy)
        o["m1_awready"] = int(bool(m1w) and sw_rdy)
        swr_rdy = any(ws[s] and i[f"s{s}_wready"] for s in range(3))
        o["m0_wready"] = int(bool(m0w) and swr_rdy)
        o["m1_wready"] = int(bool(m1w) and swr_rdy)
        bv = any(ws[s] and i[f"s{s}_bvalid"] for s in range(3))
        br = (i["s0_bresp"] if (ws[0] and i["s0_bvalid"]) else
              i["s1_bresp"] if (ws[1] and i["s1_bvalid"]) else i["s2_bresp"])
        o["m0_bvalid"] = int(bool(m0w) and bv); o["m0_bresp"] = br
        o["m1_bvalid"] = int(bool(m1w) and bv); o["m1_bresp"] = br
        # read side
        m0r = i["m0_arvalid"] and (not i["m1_arvalid"] or not rr_rd)
        m1r = i["m1_arvalid"] and (not i["m0_arvalid"] or rr_rd)
        raddr = i["m0_araddr"] if m0r else i["m1_araddr"]
        rs = [self._hit(s, raddr) for s in range(3)]
        anyr = m0r or m1r
        for s in range(3):
            o[f"s{s}_araddr"] = raddr
            o[f"s{s}_arvalid"] = int(anyr and rs[s])
            o[f"s{s}_rready"] = (i["m0_rready"] if (rs[s] and m0r) else
                                 i["m1_rready"] if (rs[s] and m1r) else 0)
        sar_rdy = any(rs[s] and i[f"s{s}_arready"] for s in range(3))
        o["m0_arready"] = int(bool(m0r) and sar_rdy)
        o["m1_arready"] = int(bool(m1r) and sar_rdy)
        rd = (i["s0_rdata"] if (rs[0] and i["s0_rvalid"]) else
              i["s1_rdata"] if (rs[1] and i["s1_rvalid"]) else i["s2_rdata"])
        rr2 = (i["s0_rresp"] if (rs[0] and i["s0_rvalid"]) else
               i["s1_rresp"] if (rs[1] and i["s1_rvalid"]) else i["s2_rresp"])
        rv = any(rs[s] and i[f"s{s}_rvalid"] for s in range(3))
        o["m0_rdata"] = rd; o["m0_rresp"] = rr2
        o["m0_rvalid"] = int(bool(m0r) and rv)
        o["m1_rdata"] = rd; o["m1_rresp"] = rr2
        o["m1_rvalid"] = int(bool(m1r) and rv)
        return o

    def step(self, ins):
        pre = self._comb(ins, self.rr, self.rr_rd)   # ready seen at the edge
        if ins["m0_awvalid"] and pre["m0_awready"]: self.rr = 1
        elif ins["m1_awvalid"] and pre["m1_awready"]: self.rr = 0
        if ins["m0_arvalid"] and pre["m0_arready"]: self.rr_rd = 1
        elif ins["m1_arvalid"] and pre["m1_arready"]: self.rr_rd = 0

    def outputs(self, ins):
        return self._comb(ins, self.rr, self.rr_rd)


# ── tilelink_router (5-port XY, contest generator 8c68299 2026-07-25) ────────
# The library's current router: 4 direction A-in/D-out ports (0=N 1=S 2=E 3=W)
# + a Local A-out/D-in port; NODE_X/NODE_Y are module PARAMETERS (not ports).
# XY decision from addr[AW-1:AW-4]=dest_x, addr[AW-5:AW-8]=dest_y; only
# LOCAL-destined packets are delivered (inter-router forwarding is wired at
# the top level — non-local packets are granted ready and consumed).
# D-channel: local response broadcast, valid gated to the current A-winner.
# Fully combinational; transcribed statement-for-statement from the RTL.
_TL_AF = [("opcode", 3), ("param", 3), ("size", 3), ("source", 4),
          ("addr", 32), ("mask", 4), ("data", 32), ("valid", 1)]
_TL_DF = [("opcode", 3), ("param", 2), ("size", 3), ("source", 4),
          ("data", 32), ("valid", 1)]


class TlRouter:
    PORTS = ([(f"p{p}_a_{n}", w, "i") for p in (0, 1, 2, 3) for n, w in _TL_AF] +
             [(f"p{p}_a_ready", 1, "o") for p in (0, 1, 2, 3)] +
             [(f"p{p}_d_{n}", w, "o") for p in (0, 1, 2, 3) for n, w in _TL_DF] +
             [(f"p{p}_d_ready", 1, "i") for p in (0, 1, 2, 3)] +
             [(f"loc_a_{n}", w, "o") for n, w in _TL_AF] +
             [("loc_a_ready", 1, "i")] +
             [(f"loc_d_{n}", w, "i") for n, w in _TL_DF] +
             [("loc_d_ready", 1, "o")])
    CLKS = [("clk", "rst_n")]

    def __init__(self, node_x=1, node_y=1, data_width=32, addr_width=32):
        self.nx, self.ny, self.aw = node_x & 0xF, node_y & 0xF, addr_width

    def step(self, ins):
        pass                                        # purely combinational

    def outputs(self, i):
        v = [int(bool(i[f"p{p}_a_valid"])) for p in (0, 1, 2, 3)]
        any_in = int(any(v))
        # RTL priority mux p0>p1>p2>p3 falls through to p3 when none valid
        sel = 0 if v[0] else 1 if v[1] else 2 if v[2] else 3
        f = {n: i[f"p{sel}_a_{n}"] for n, _ in _TL_AF}
        dest_x = (f["addr"] >> (self.aw - 4)) & 0xF
        dest_y = (f["addr"] >> (self.aw - 8)) & 0xF
        go_local = any_in and dest_x == self.nx and dest_y == self.ny
        go_dir = any_in and not go_local        # east/west/north/south cases
        o = {f"loc_a_{n}": f[n] for n, _ in _TL_AF if n != "valid"}
        o["loc_a_valid"] = int(bool(go_local))
        la = int(bool(i["loc_a_ready"]))
        grant = la if go_local else (1 if go_dir else 0)
        o["p0_a_ready"] = int(bool(v[0] and grant))
        o["p1_a_ready"] = int(bool(not v[0] and v[1] and (la if go_local else 1)))
        o["p2_a_ready"] = int(bool(not v[0] and not v[1] and v[2]
                                   and (la if go_local else 1)))
        o["p3_a_ready"] = int(bool(not v[0] and not v[1] and not v[2] and v[3]
                                   and (la if go_local else 1)))
        winner = [v[0], not v[0] and v[1], not v[0] and not v[1] and v[2],
                  not v[0] and not v[1] and not v[2] and v[3]]
        for p in (0, 1, 2, 3):
            for n, _ in _TL_DF:
                if n != "valid":
                    o[f"p{p}_d_{n}"] = i[f"loc_d_{n}"]
            o[f"p{p}_d_valid"] = int(bool(i["loc_d_valid"] and winner[p]))
        o["loc_d_ready"] = int(bool(i["p0_d_ready"] or i["p1_d_ready"]
                                    or i["p2_d_ready"] or i["p3_d_ready"]))
        return o


# ── tilelink_ni (AXI4-Lite -> TL-UL bridge) ───────────────────────────────────
class TlNi:
    S_IDLE, S_SEND, S_WAIT = 0, 1, 2
    PORTS = [("axi_awaddr", 32, "i"), ("axi_awvalid", 1, "i"), ("axi_awready", 1, "o"),
             ("axi_wdata", 32, "i"), ("axi_wstrb", 4, "i"), ("axi_wvalid", 1, "i"),
             ("axi_wready", 1, "o"), ("axi_bresp", 2, "o"), ("axi_bvalid", 1, "o"),
             ("axi_bready", 1, "i"), ("axi_araddr", 32, "i"), ("axi_arvalid", 1, "i"),
             ("axi_arready", 1, "o"), ("axi_rdata", 32, "o"), ("axi_rresp", 2, "o"),
             ("axi_rvalid", 1, "o"), ("axi_rready", 1, "i"),
             ("tl_a_opcode", 3, "o"), ("tl_a_param", 3, "o"), ("tl_a_size", 3, "o"),
             ("tl_a_source", 4, "o"), ("tl_a_addr", 32, "o"), ("tl_a_mask", 4, "o"),
             ("tl_a_data", 32, "o"), ("tl_a_valid", 1, "o"), ("tl_a_ready", 1, "i"),
             ("tl_d_opcode", 3, "i"), ("tl_d_param", 2, "i"), ("tl_d_size", 3, "i"),
             ("tl_d_source", 4, "i"), ("tl_d_data", 32, "i"), ("tl_d_valid", 1, "i"),
             ("tl_d_ready", 1, "o")]
    CLKS = [("clk", "rst_n")]

    def __init__(self, data_width=32, addr_width=32):
        self.st = self.S_IDLE
        self.r_addr = self.r_wdata = self.r_mask = self.is_write = 0

    def step(self, ins):
        if self.st == self.S_IDLE:
            if ins["axi_awvalid"] and ins["axi_wvalid"]:
                self.r_addr, self.r_wdata = ins["axi_awaddr"], ins["axi_wdata"]
                self.r_mask, self.is_write = ins["axi_wstrb"], 1
                self.st = self.S_SEND
            elif ins["axi_arvalid"] and not ins["axi_awvalid"]:
                self.r_addr, self.is_write = ins["axi_araddr"], 0
                self.st = self.S_SEND
        elif self.st == self.S_SEND:
            if ins["tl_a_ready"]: self.st = self.S_WAIT
        elif self.st == self.S_WAIT:
            if ins["tl_d_valid"]: self.st = self.S_IDLE

    def outputs(self, i):
        idle = self.st == self.S_IDLE
        return dict(
            axi_awready=int(idle and i["axi_awvalid"] and not self.is_write),
            axi_wready=int(idle and i["axi_wvalid"] and i["axi_awvalid"]),
            axi_arready=int(idle and i["axi_arvalid"] and not i["axi_awvalid"]),
            axi_bvalid=int(idle and self.is_write and i["tl_d_valid"]
                           and i["tl_d_opcode"] == 0),
            axi_bresp=0,
            axi_rvalid=int(idle and not self.is_write and i["tl_d_valid"]
                           and i["tl_d_opcode"] == 1),
            axi_rdata=i["tl_d_data"], axi_rresp=0,
            tl_a_opcode=0 if self.is_write else 4, tl_a_param=0, tl_a_size=2,
            tl_a_source=0, tl_a_addr=self.r_addr,
            tl_a_mask=self.r_mask if self.is_write else 0xF,
            tl_a_data=self.r_wdata, tl_a_valid=int(self.st == self.S_SEND),
            tl_d_ready=int(self.st == self.S_WAIT or i["axi_bready"]
                           or i["axi_rready"]))


# ── aes128 (library core: ENCRYPT-ONLY — the `encrypt` input is ignored) ──────
_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]
_RCON = [0, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _byte(x, i): return (x >> i * 8) & 0xFF


def _setb(x, i, v): return (x & ~(0xFF << i * 8)) | ((v & 0xFF) << i * 8)


def _sub_bytes(s):
    r = 0
    for i in range(16):
        r = _setb(r, i, _SBOX[_byte(s, i)])
    return r


_SHIFT_MAP = [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11]


def _shift_rows(s):
    r = 0
    for i in range(16):
        r = _setb(r, i, _byte(s, _SHIFT_MAP[i]))
    return r


def _xtime(b): return ((b << 1) ^ (0x1B if b & 0x80 else 0)) & 0xFF


def _mix_col(c):
    s = [_byte(c, i) for i in range(4)]
    return ((_xtime(s[3]) ^ s[0] ^ s[1] ^ _xtime(s[2]) ^ s[2] ^ s[3]) << 24 |
            (_xtime(s[2]) ^ s[3] ^ s[0] ^ _xtime(s[1]) ^ s[1] ^ s[2]) << 16 |
            (_xtime(s[1]) ^ s[2] ^ s[3] ^ _xtime(s[0]) ^ s[0] ^ s[1]) << 8 |
            (_xtime(s[0]) ^ s[1] ^ s[2] ^ _xtime(s[3]) ^ s[3] ^ s[0]))


def _mix_columns(s):
    r = 0
    for c in range(4):
        r |= _mix_col((s >> c * 32) & M32) << c * 32
    return r


def _expand_key(key):
    rk = [key]
    for i in range(1, 11):
        prev = rk[i - 1]
        t = prev & M32                              # last word
        t = (((_SBOX[(t >> 16) & 0xFF] ^ _RCON[i]) << 24) |
             (_SBOX[(t >> 8) & 0xFF] << 16) |
             (_SBOX[t & 0xFF] << 8) | _SBOX[(t >> 24) & 0xFF])
        w3 = ((prev >> 96) & M32) ^ t
        w2 = ((prev >> 64) & M32) ^ w3
        w1 = ((prev >> 32) & M32) ^ w2
        w0 = (prev & M32) ^ w1
        rk.append((w3 << 96) | (w2 << 64) | (w1 << 32) | w0)
    return rk


class Aes128:
    PORTS = [("key_in", 128, "i"), ("key_valid", 1, "i"),
             ("data_in", 128, "i"), ("start", 1, "i"), ("encrypt", 1, "i"),
             ("data_out", 128, "o"), ("done", 1, "o"), ("busy", 1, "o")]
    CLKS = [("clk", "rst_n")]

    def __init__(self):
        self.rk = [0] * 11
        self.state_r = self.data_out = 0
        self.running = self.round_cnt = self.done = 0

    def step(self, ins):
        o_running, o_cnt, o_state = self.running, self.round_cnt, self.state_r
        self.done = 0
        if ins["key_valid"]:
            self.rk = _expand_key(ins["key_in"])   # task = blocking, same edge
        if ins["start"] and not o_running:
            self.state_r = ins["data_in"] ^ self.rk[0]
            self.running, self.round_cnt = 1, 1
        elif o_running:
            if o_cnt < 10:
                self.state_r = _mix_columns(_shift_rows(_sub_bytes(o_state))) \
                    ^ self.rk[o_cnt]
                self.round_cnt = o_cnt + 1
            else:
                self.data_out = _shift_rows(_sub_bytes(o_state)) ^ self.rk[10]
                self.done, self.running = 1, 0

    def outputs(self, ins):
        return dict(data_out=self.data_out, done=self.done, busy=self.running)


MODELS = {
    "sync_fifo": SyncFifo, "async_fifo": AsyncFifo, "sram_sp": SramSp,
    "sram_dp": SramDp, "cdc_sync": CdcSync, "perf_counter": PerfCounter,
    "axi_lite_sram": AxiLiteSram, "dma_engine": DmaEngine,
    "axi_lite_crossbar": AxiLiteXbar, "tilelink_router": TlRouter,
    "tilelink_ni": TlNi, "aes128": Aes128,
}
