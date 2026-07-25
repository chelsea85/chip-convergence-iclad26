// distributed under the mit license
// https://opensource.org/licenses/mit-license.php

`timescale 1 ns / 1 ps
`default_nettype none

module wptr_full

	#(
		parameter ADDRSIZE = 4
	)(
		input  wire                wclk,
		input  wire                wrst_n,
		input  wire                winc,
		input  wire [ADDRSIZE  :0] wq2_rptr,
		output reg                 wfull,
		output reg                 awfull,
		output wire [ADDRSIZE-1:0] waddr,
		output wire [ADDRSIZE  :0] wptr
	);

    reg  [ADDRSIZE:0] wbin;
    wire [ADDRSIZE:0] wbinnext;
    wire              awfull_val, wfull_val;

	// GRAYSTYLE2 pointer — register only the binary counter.
	// The gray pointer is a pure function of the registered binary value
	// (wptr == gray(wbin)), so storing it separately is redundant. Deriving it
	// combinationally removes ADDRSIZE+1 flip-flops while keeping the exact same
	// value sequence (1-bit-change CDC property preserved: wbin is stable between
	// wclk edges, so wptr presented to the synchronizer is stable too).
	always @(posedge wclk or negedge wrst_n) begin

		if (!wrst_n)
			wbin <= 0;
		else
			wbin <= wbinnext;

	end

	assign wptr = (wbin >> 1) ^ wbin;   // gray(wbin) == previously-registered wptr

    // Memory write-address pointer (okay to use binary to address memory)
    assign waddr = wbin[ADDRSIZE-1:0];

    // Late-arriving control signal
    wire wincr = winc & ~wfull;

    // Precompute incremented binary values (independent of wincr)
    wire [ADDRSIZE:0] wbin_p1 = wbin + 1'b1;
    wire [ADDRSIZE:0] wbin_p2 = wbin + 2'd2;

    // Precompute gray codes for both possible branches
    wire [ADDRSIZE:0] wgray_p1 = (wbin_p1 >> 1) ^ wbin_p1;
    wire [ADDRSIZE:0] wgray_p2 = (wbin_p2 >> 1) ^ wbin_p2;

    // Decode synchronized read pointer
    wire [ADDRSIZE:0] wq2_rptr_dec = {~wq2_rptr[ADDRSIZE:ADDRSIZE-1], wq2_rptr[ADDRSIZE-2:0]};

    // Precompute full conditions for wincr == 0 and wincr == 1
    wire wfull_val_0 = (wptr == wq2_rptr_dec);
    wire wfull_val_1 = (wgray_p1 == wq2_rptr_dec);

    wire awfull_val_0 = (wgray_p1 == wq2_rptr_dec);
    wire awfull_val_1 = (wgray_p2 == wq2_rptr_dec);

    // Late-select multiplexing
    assign wbinnext   = wincr ? wbin_p1 : wbin;
    assign wfull_val  = wincr ? wfull_val_1 : wfull_val_0;
    assign awfull_val = wincr ? awfull_val_1 : awfull_val_0;

     always @(posedge wclk or negedge wrst_n) begin

        if (!wrst_n) begin
            awfull <= 1'b0;
            wfull  <= 1'b0;
        end else begin
            awfull <= awfull_val;
            wfull  <= wfull_val;
        end
    end

endmodule

`resetall
