# Permanent keyless geometric safety controls for the ASU v2 passes (Rev3 —
# Codex Rev2 review §6). Runs inside the pinned KLayout image:
#   klayout -b -r test_controls.py        (exits nonzero on any failure)
# Each control constructs a small synthetic layout (dbu = 0.25 nm, 4 dbu/nm,
# matching the block testcases), executes the EMITTED pass code exactly as the
# organizer's render would, and asserts the accept/reject decision.
import pya, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
import v2_repairs  # noqa: E402

FAILURES = []


def new_layout():
    ly = pya.Layout()
    ly.dbu = 0.00025
    ly.create_cell("TOP")
    return ly


def put(ly, layer, box):
    top = ly.top_cell()
    top.shapes(ly.layer(pya.LayerInfo(layer, 0))).insert(box)


def run_pass(ly, code):
    ns = {"pya": pya, "layout": ly}
    exec(code, ns)
    return ns


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print("[control] %-38s %s %s" % (name, status, detail))
    if not cond:
        FAILURES.append(name)


# ── via-bar-safe controls (Codex Rev2 §3) ────────────────────────────────────
def bar_layout(with_island, drop_rail=False):
    ly = new_layout()
    # below metal M4 (layer 40): one rail under the cuts
    if drop_rail:
        put(ly, 40, pya.Box(0, 150, 1000, 200))       # only under cut tops
    else:
        put(ly, 40, pya.Box(0, 52, 1000, 148))
    # upper metal M5 (layer 50): horizontal landing, U-shaped via a notch
    put(ly, 50, pya.Box(0, 0, 400, 200))
    put(ly, 50, pya.Box(600, 0, 1000, 200))
    put(ly, 50, pya.Box(0, 150, 1000, 200))           # bridge -> one U polygon
    if with_island:
        put(ly, 50, pya.Box(450, 20, 550, 120))       # separate M5 island
    # two flagged V4 cuts (96 tall < landing 200)
    if drop_rail:
        put(ly, 45, pya.Box(100, 104, 196, 200))      # touch the top rail
        put(ly, 45, pya.Box(800, 104, 896, 200))
    else:
        put(ly, 45, pya.Box(100, 52, 196, 148))
        put(ly, 45, pya.Box(800, 52, 896, 148))
    return ly


code_bar = v2_repairs.via_bar_safe_pass()

ns = run_pass(bar_layout(with_island=False), code_bar)
check("bar/positive (no island) accepts", ns["_asu_vb"]["bars"] >= 1,
      str(ns["_asu_vb"]))

ns = run_pass(bar_layout(with_island=True), code_bar)
check("bar/upper-island short rejects", ns["_asu_vb"]["bars"] == 0
      and ns["_asu_vb"]["bar_skip_la"] >= 1, str(ns["_asu_vb"]))

ns = run_pass(bar_layout(with_island=False, drop_rail=True), code_bar)
check("bar/dropped-below-contact rejects", ns["_asu_vb"]["bars"] == 0
      and ns["_asu_vb"]["bar_skip_la"] >= 1, str(ns["_asu_vb"]))

# ── track-shift controls (Codex Rev2 §4) ─────────────────────────────────────
code_ts = v2_repairs.track_shift_pass()

def swap_layout():
    # off-pitch min-width M4 track y=48..144 (P=192 -> d1=-48 to 0..96,
    # d2=+144 to 192..288); stationary V4-A contacts only before, V4-B only
    # after d1, V4-C only after d2; unrelated M1 joins A/B in projection.
    ly = new_layout()
    put(ly, 40, pya.Box(100, 48, 516, 144))
    put(ly, 45, pya.Box(200, 134, 296, 230))          # V4-A (before only)
    put(ly, 45, pya.Box(300, -86, 396, 10))           # V4-B (after d1 only)
    put(ly, 45, pya.Box(420, 278, 516, 374))          # V4-C (after d2 only)
    put(ly, 50, pya.Box(150, 230, 350, 330))          # M5-A
    put(ly, 50, pya.Box(250, -190, 450, -86))         # M5-B
    put(ly, 19, pya.Box(150, -190, 350, 330))         # unrelated M1 projection
    return ly

ns = run_pass(swap_layout(), code_ts)
check("track/projection-swap rejects", ns["_asu_ts"]["moved"] == 0
      and ns["_asu_ts"]["skipped"] == 1, str(ns["_asu_ts"]))

def clean_track_layout():
    # off-pitch M4 track with riding V3 + V4 cuts, ample hosts everywhere
    ly = new_layout()
    put(ly, 40, pya.Box(100, 48, 516, 144))
    put(ly, 35, pya.Box(200, 48, 272, 144))           # riding V3
    put(ly, 30, pya.Box(200, -800, 272, 900))         # long M3 host below
    put(ly, 45, pya.Box(390, 48, 486, 144))           # riding V4
    put(ly, 50, pya.Box(384, -800, 480, 900))         # long M5 host (on pitch)
    return ly

ns = run_pass(clean_track_layout(), code_ts)
check("track/clean move accepts", ns["_asu_ts"]["moved"] == 1,
      str(ns["_asu_ts"]))

def patch_foreign_layout():
    # riding V3 cut on a short M3 rail; foreign V2 bars sit exactly where the
    # end-cap patch would go for BOTH grid candidates -> zero accepted moves
    ly = new_layout()
    put(ly, 40, pya.Box(100, 48, 516, 144))
    put(ly, 35, pya.Box(200, 50, 272, 142))           # riding V3 (in track)
    put(ly, 30, pya.Box(200, 30, 272, 170))           # short M3 host rail
    put(ly, 25, pya.Box(200, -100, 272, 28))          # foreign V2 below end
    put(ly, 25, pya.Box(200, 172, 272, 300))          # foreign V2 above end
    return ly

ns = run_pass(patch_foreign_layout(), code_ts)
check("track/patch-foreign-via rejects", ns["_asu_ts"]["moved"] == 0,
      str(ns["_asu_ts"]))

def m6v6_layout():
    ly = new_layout()
    put(ly, 60, pya.Box(0, 40, 2000, 168))            # off-grid M6 (G=128)
    put(ly, 65, pya.Box(500, 40, 628, 168))           # V6 riding it
    return ly

ns = run_pass(m6v6_layout(), code_ts)
check("track/M6-V6 refusal", ns["_asu_ts"]["moved"] == 0
      and ns["_asu_ts"]["skip_upper"] == 1, str(ns["_asu_ts"]))

# ── v1-patch control ─────────────────────────────────────────────────────────
code_v1 = v2_repairs.v1_patch_pass()

def v1_foreign_layout(foreign):
    # V1 hanging off its pad edge (needs a patch); optionally a foreign V0
    # right in the patch zone -> reject
    ly = new_layout()
    put(ly, 19, pya.Box(0, 0, 300, 400))              # host M1 pad
    put(ly, 21, pya.Box(280, 150, 352, 222))          # V1 overhangs right edge
    if foreign:
        put(ly, 18, pya.Box(352, 150, 424, 222))      # foreign V0 in patch zone
    return ly

ns = run_pass(v1_foreign_layout(foreign=False), code_v1)
check("v1-patch/positive accepts", ns["_asu_v1"]["v1_patched"] == 1,
      str(ns["_asu_v1"]))
ns = run_pass(v1_foreign_layout(foreign=True), code_v1)
check("v1-patch/foreign-via rejects", ns["_asu_v1"]["v1_patched"] == 0,
      str(ns["_asu_v1"]))

print("[controls] %d failure(s)" % len(FAILURES))
if FAILURES:
    sys.exit(1)
