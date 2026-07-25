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
    wire [ADDRSIZE:0] wgraynext, wbinnext, wgraynextp1;
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
    assign wbinnext  = wbin + ((winc & ~wfull) ? 1 : 0);
    assign wgraynext = (wbinnext >> 1) ^ wbinnext;
    assign wgraynextp1 = ((wbinnext + 1'b1) >> 1) ^ (wbinnext + 1'b1);

    //------------------------------------------------------------------
    // Simplified version of the three necessary full-tests:
    // assign wfull_val=((wgnext[ADDRSIZE] !=wq2_rptr[ADDRSIZE] ) &&
    //                   (wgnext[ADDRSIZE-1]  !=wq2_rptr[ADDRSIZE-1]) &&
    // (wgnext[ADDRSIZE-2:0]==wq2_rptr[ADDRSIZE-2:0]));
    //------------------------------------------------------------------

     assign wfull_val = (wgraynext == {~wq2_rptr[ADDRSIZE:ADDRSIZE-1],wq2_rptr[ADDRSIZE-2:0]});
     assign awfull_val = (wgraynextp1 == {~wq2_rptr[ADDRSIZE:ADDRSIZE-1],wq2_rptr[ADDRSIZE-2:0]});

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
