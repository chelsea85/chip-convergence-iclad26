// =============================================================================
// secure_periph_soc.v  — NXP ICLAD 2026 EASY top-level integration
// Hand-written stitching of library-generated IPs per architecture.html.
//   CPU (AHB-Lite) -> ahb_to_apb_bridge -> apb_fabric5 -> {UART,GPIO,TIMER,WDT,IRQA}
//   reset_sync generates sys_rst_n (async-assert on POR or WDT reset).
//   irq_aggregator collects peripheral IRQs -> cpu_irq / cpu_irq_id.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module secure_periph_soc (
    input  wire        clk,
    input  wire        por_n,
    // AHB-Lite CPU master port
    input  wire [31:0] cpu_haddr,
    input  wire [1:0]  cpu_htrans,
    input  wire        cpu_hwrite,
    input  wire [2:0]  cpu_hsize,
    input  wire [2:0]  cpu_hburst,
    input  wire [2:0]  cpu_hprot,
    input  wire [31:0] cpu_hwdata,
    output wire [31:0] cpu_hrdata,
    output wire        cpu_hready,
    output wire [1:0]  cpu_hresp,
    // GPIO
    input  wire [31:0] gpio_in,
    output wire [31:0] gpio_out,
    output wire [31:0] gpio_oe,
    // UART
    output wire        uart_tx,
    input  wire        uart_rx,
    input  wire        uart_cts_n,
    output wire        uart_rts_n,
    // PWM
    output wire        pwm0,
    output wire        pwm1,
    // Interrupt to CPU
    output wire        cpu_irq,
    output wire [2:0]  cpu_irq_id,
    // Watchdog reset output
    output wire        wdt_rst_req
);
    // ── Reset ──────────────────────────────────────────────────────────────
    wire sys_rst_n;
    reset_sync #(.STAGES(3)) u_reset_sync (
        .clk       (clk),
        .por_n     (por_n),
        .wdt_rst_n (~wdt_rst_req),   // async-assert on watchdog stage-2 reset
        .sys_rst_n (sys_rst_n)
    );

    // ── Bridge APB master <-> fabric ────────────────────────────────────────
    wire        m_psel, m_penable, m_pwrite, m_pready, m_pslverr;
    wire [31:0] m_paddr, m_pwdata, m_prdata;
    wire [2:0]  m_pprot;

    ahb_to_apb_bridge u_bridge (
        .hclk      (clk),
        .hresetn   (sys_rst_n),
        .haddr     (cpu_haddr),
        .htrans    (cpu_htrans),
        .hwrite    (cpu_hwrite),
        .hsize     (cpu_hsize),
        .hburst    (cpu_hburst),
        .hprot     (cpu_hprot),
        .hwdata    (cpu_hwdata),
        .hsel      (1'b1),
        .hready_in (1'b1),
        .hrdata    (cpu_hrdata),
        .hready_out(cpu_hready),
        .hresp     (cpu_hresp),
        .psel      (m_psel),
        .penable   (m_penable),
        .pwrite    (m_pwrite),
        .paddr     (m_paddr),
        .pwdata    (m_pwdata),
        .pprot     (m_pprot),
        .prdata    (m_prdata),
        .pready    (m_pready),
        .pslverr   (m_pslverr)
    );

    // ── Per-slave APB wires ─────────────────────────────────────────────────
    wire        s0_psel,s0_penable,s0_pwrite,s0_pready,s0_pslverr;
    wire [11:0] s0_paddr; wire [31:0] s0_pwdata,s0_prdata;
    wire        s1_psel,s1_penable,s1_pwrite,s1_pready,s1_pslverr;
    wire [11:0] s1_paddr; wire [31:0] s1_pwdata,s1_prdata;
    wire        s2_psel,s2_penable,s2_pwrite,s2_pready,s2_pslverr;
    wire [11:0] s2_paddr; wire [31:0] s2_pwdata,s2_prdata;
    wire        s3_psel,s3_penable,s3_pwrite,s3_pready,s3_pslverr;
    wire [11:0] s3_paddr; wire [31:0] s3_pwdata,s3_prdata;
    wire        s4_psel,s4_penable,s4_pwrite,s4_pready,s4_pslverr;
    wire [11:0] s4_paddr; wire [31:0] s4_pwdata,s4_prdata;

    apb_fabric5 #(.TIMEOUT_CYC(16)) u_fabric (
        .pclk(clk), .presetn(sys_rst_n),
        .m_psel(m_psel), .m_penable(m_penable), .m_pwrite(m_pwrite),
        .m_paddr(m_paddr), .m_pwdata(m_pwdata), .m_pprot(m_pprot),
        .m_prdata(m_prdata), .m_pready(m_pready), .m_pslverr(m_pslverr),
        .s0_psel(s0_psel),.s0_penable(s0_penable),.s0_pwrite(s0_pwrite),.s0_paddr(s0_paddr),
        .s0_pwdata(s0_pwdata),.s0_prdata(s0_prdata),.s0_pready(s0_pready),.s0_pslverr(s0_pslverr),
        .s1_psel(s1_psel),.s1_penable(s1_penable),.s1_pwrite(s1_pwrite),.s1_paddr(s1_paddr),
        .s1_pwdata(s1_pwdata),.s1_prdata(s1_prdata),.s1_pready(s1_pready),.s1_pslverr(s1_pslverr),
        .s2_psel(s2_psel),.s2_penable(s2_penable),.s2_pwrite(s2_pwrite),.s2_paddr(s2_paddr),
        .s2_pwdata(s2_pwdata),.s2_prdata(s2_prdata),.s2_pready(s2_pready),.s2_pslverr(s2_pslverr),
        .s3_psel(s3_psel),.s3_penable(s3_penable),.s3_pwrite(s3_pwrite),.s3_paddr(s3_paddr),
        .s3_pwdata(s3_pwdata),.s3_prdata(s3_prdata),.s3_pready(s3_pready),.s3_pslverr(s3_pslverr),
        .s4_psel(s4_psel),.s4_penable(s4_penable),.s4_pwrite(s4_pwrite),.s4_paddr(s4_paddr),
        .s4_pwdata(s4_pwdata),.s4_prdata(s4_prdata),.s4_pready(s4_pready),.s4_pslverr(s4_pslverr)
    );

    // ── Peripheral IRQ lines ────────────────────────────────────────────────
    wire uart_irq, gpio_irq, timer_irq, wdt_irq;
    wire [2*32-1:0] gpio_alt;   // unused alt-function bus

    // S0: UART @ 0x0000_0000
    apb_uart #(.FIFO_DEPTH(16), .DEFAULT_DIV(26)) u_uart (
        .pclk(clk), .presetn(sys_rst_n),
        .psel(s0_psel), .penable(s0_penable), .pwrite(s0_pwrite),
        .paddr(s0_paddr), .pwdata(s0_pwdata),
        .prdata(s0_prdata), .pready(s0_pready), .pslverr(s0_pslverr),
        .uart_tx(uart_tx), .uart_rx(uart_rx),
        .cts_n(uart_cts_n), .rts_n(uart_rts_n), .irq(uart_irq)
    );

    // S1: GPIO @ 0x0000_1000
    apb_gpio #(.GPIO_WIDTH(32), .DBS(3)) u_gpio (
        .pclk(clk), .presetn(sys_rst_n),
        .psel(s1_psel), .penable(s1_penable), .pwrite(s1_pwrite),
        .paddr(s1_paddr), .pwdata(s1_pwdata),
        .prdata(s1_prdata), .pready(s1_pready), .pslverr(s1_pslverr),
        .gpio_in(gpio_in), .gpio_out(gpio_out), .gpio_oe(gpio_oe),
        .alt_func(gpio_alt), .irq(gpio_irq)
    );

    // S2: TIMER @ 0x0000_2000
    apb_timer #(.CHANNELS(2), .WIDTH(32)) u_timer (
        .pclk(clk), .presetn(sys_rst_n),
        .psel(s2_psel), .penable(s2_penable), .pwrite(s2_pwrite),
        .paddr(s2_paddr), .pwdata(s2_pwdata),
        .prdata(s2_prdata), .pready(s2_pready), .pslverr(s2_pslverr),
        .pwm0(pwm0), .pwm1(pwm1), .irq(timer_irq)
    );

    // S3: WATCHDOG @ 0x0000_3000 (privileged)
    apb_watchdog u_wdt (
        .pclk(clk), .presetn(sys_rst_n),
        .psel(s3_psel), .penable(s3_penable), .pwrite(s3_pwrite),
        .paddr(s3_paddr), .pwdata(s3_pwdata),
        .prdata(s3_prdata), .pready(s3_pready), .pslverr(s3_pslverr),
        .wdt_irq(wdt_irq), .wdt_rst_req(wdt_rst_req)
    );

    // S4: IRQ AGGREGATOR @ 0x0000_4000
    //  src map: [1]=uart [2]=gpio [3]=timer [4]=wdt [5]=wdt_rst ; [0],[6],[7] reserved/sw
    wire [7:0] irq_src = {1'b0, 1'b0, wdt_rst_req, wdt_irq,
                          timer_irq, gpio_irq, uart_irq, 1'b0};
    irq_aggregator u_irqa (
        .pclk(clk), .presetn(sys_rst_n),
        .psel(s4_psel), .penable(s4_penable), .pwrite(s4_pwrite),
        .paddr(s4_paddr), .pwdata(s4_pwdata),
        .prdata(s4_prdata), .pready(s4_pready), .pslverr(s4_pslverr),
        .irq_src(irq_src), .cpu_irq(cpu_irq), .cpu_irq_id(cpu_irq_id)
    );

endmodule

`resetall
