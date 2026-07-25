//======================================================================
//
// sha512_w_mem_regs.v
// -------------------
// The W memory for the SHA-512 core. This version uses 16
// 32-bit registers as a sliding window to generate the 64 words.
//
//
// Author: Joachim Strombergson
// Copyright (c) 2014 Secworks Sweden AB
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or
// without modification, are permitted provided that the following
// conditions are met:
//
// 1. Redistributions of source code must retain the above copyright
//    notice, this list of conditions and the following disclaimer.
//
// 2. Redistributions in binary form must reproduce the above copyright
//    notice, this list of conditions and the following disclaimer in
//    the documentation and/or other materials provided with the
//    distribution.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
// FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
// COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
// INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
// BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
// LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
// CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
// STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
// ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
//
//======================================================================

`default_nettype none

module sha512_w_mem(
                    input wire            clk,
                    input wire            reset_n,

                    input wire [1023 : 0] block,

                    input wire            init,
                    input wire            next,
                    output wire [63 : 0]  w
                   );


  //----------------------------------------------------------------
  // Registers including update variables and write enable.
  //----------------------------------------------------------------
  reg [63 : 0] w_mem [0 : 15];
  reg [63 : 0] w_mem00_new;
  reg [63 : 0] w_mem01_new;
  reg [63 : 0] w_mem02_new;
  reg [63 : 0] w_mem03_new;
  reg [63 : 0] w_mem04_new;
  reg [63 : 0] w_mem05_new;
  reg [63 : 0] w_mem06_new;
  reg [63 : 0] w_mem07_new;
  reg [63 : 0] w_mem08_new;
  reg [63 : 0] w_mem09_new;
  reg [63 : 0] w_mem10_new;
  reg [63 : 0] w_mem11_new;
  reg [63 : 0] w_mem12_new;
  reg [63 : 0] w_mem13_new;
  reg [63 : 0] w_mem14_new;
  reg [63 : 0] w_mem15_new;
  reg          w_mem_we;

  reg [6 : 0] w_ctr_reg;
  reg [6 : 0] w_ctr_new;
  reg         w_ctr_we;


  //----------------------------------------------------------------
  // Wires.
  //----------------------------------------------------------------
  reg [63 : 0] w_tmp;
  reg [63 : 0] w_new;

  // Declarations moved to module scope for Kogge-Stone adder connections
  reg [63 : 0] w_s1;
  reg [63 : 0] w_c1;
  reg [63 : 0] w_s2;
  reg [63 : 0] w_c2;
  reg [63 : 0] w_c1_tmp;
  reg [63 : 0] w_c2_tmp;

  wire [63 : 0] w_new_ks;


  //----------------------------------------------------------------
  // Concurrent connectivity for ports etc.
  //----------------------------------------------------------------
  assign w = w_tmp;


  //----------------------------------------------------------------
  // Module instantiations.
  //----------------------------------------------------------------
  kogge_stone_64_wmem ks_w_new (
    .A(w_s2),
    .B(w_c2),
    .S(w_new_ks)
  );


  //----------------------------------------------------------------
  // reg_update
  // Update functionality for all registers in the core.
  // All registers are positive edge triggered with asynchronous
  // active low reset. All registers have write enable.
  //----------------------------------------------------------------
  always @ (posedge clk or negedge reset_n)
    begin : reg_update
      integer i;

      if (!reset_n)
        begin
          for (i = 0; i < 16; i = i + 1)
            w_mem[i] <= 64'h0;

          w_ctr_reg <= 7'h0;
        end
      else
        begin
          if (w_mem_we)
            begin
              w_mem[00] <= w_mem00_new;
              w_mem[01] <= w_mem01_new;
              w_mem[02] <= w_mem02_new;
              w_mem[03] <= w_mem03_new;
              w_mem[04] <= w_mem04_new;
              w_mem[05] <= w_mem05_new;
              w_mem[06] <= w_mem06_new;
              w_mem[07] <= w_mem07_new;
              w_mem[08] <= w_mem08_new;
              w_mem[09] <= w_mem09_new;
              w_mem[10] <= w_mem10_new;
              w_mem[11] <= w_mem11_new;
              w_mem[12] <= w_mem12_new;
              w_mem[13] <= w_mem13_new;
              w_mem[14] <= w_mem14_new;
              w_mem[15] <= w_mem15_new;
            end

          if (w_ctr_we)
              w_ctr_reg <= w_ctr_new;
        end
    end // reg_update


  //----------------------------------------------------------------
  // select_w
  //
  // Mux for the external read operation. This is where we exract
  // the W variable.
  //----------------------------------------------------------------
  always @*
    begin : select_w
      if (w_ctr_reg < 16)
        w_tmp = w_mem[w_ctr_reg[3 : 0]];
      else
        w_tmp = w_new;
    end // select_w


  //----------------------------------------------------------------
  // w_new_logic
  //
  // Logic that calculates the next value to be inserted into
  // the sliding window of the memory.
  //----------------------------------------------------------------
  always @*
    begin : w_mem_update_logic
      reg [63 : 0] w_0;
      reg [63 : 0] w_1;
      reg [63 : 0] w_9;
      reg [63 : 0] w_14;
      reg [63 : 0] d0;
      reg [63 : 0] d1;

      w_mem00_new = 64'h0;
      w_mem01_new = 64'h0;
      w_mem02_new = 64'h0;
      w_mem03_new = 64'h0;
      w_mem04_new = 64'h0;
      w_mem05_new = 64'h0;
      w_mem06_new = 64'h0;
      w_mem07_new = 64'h0;
      w_mem08_new = 64'h0;
      w_mem09_new = 64'h0;
      w_mem10_new = 64'h0;
      w_mem11_new = 64'h0;
      w_mem12_new = 64'h0;
      w_mem13_new = 64'h0;
      w_mem14_new = 64'h0;
      w_mem15_new = 64'h0;
      w_mem_we    = 0;

      w_s1 = 64'h0; w_c1 = 64'h0;
      w_s2 = 64'h0; w_c2 = 64'h0;
      w_c1_tmp = 64'h0;
      w_c2_tmp = 64'h0;

      w_0  = w_mem[0];
      w_1  = w_mem[1];
      w_9  = w_mem[9];
      w_14 = w_mem[14];

      d0 = {w_1[0],     w_1[63 : 1]} ^ // ROTR1
           {w_1[7 : 0], w_1[63 : 8]} ^ // ROTR8
           {7'b0000000, w_1[63 : 7]};  // SHR7

      d1 = {w_14[18 : 0], w_14[63 : 19]} ^ // ROTR19
           {w_14[60 : 0], w_14[63 : 61]} ^ // ROTR61
           {6'b000000,    w_14[63 : 6]};   // SHR6

      // CSA tree for w_new (4 operands)
      // Reduces 4-operand carry-propagate addition to 2 levels of carry-save reduction.
      w_s1 = w_0 ^ d0 ^ w_9;
      w_c1_tmp = (w_0 & d0) | (d0 & w_9) | (w_9 & w_0);
      w_c1 = {w_c1_tmp[62:0], 1'b0};

      w_s2 = w_s1 ^ w_c1 ^ d1;
      w_c2_tmp = (w_s1 & w_c1) | (w_c1 & d1) | (d1 & w_s1);
      w_c2 = {w_c2_tmp[62:0], 1'b0};

      w_new = w_new_ks;

      if (init)
        begin
          w_mem00_new = block[1023 : 960];
          w_mem01_new = block[959  : 896];
          w_mem02_new = block[895  : 832];
          w_mem03_new = block[831  : 768];
          w_mem04_new = block[767  : 704];
          w_mem05_new = block[703  : 640];
          w_mem06_new = block[639  : 576];
          w_mem07_new = block[575  : 512];
          w_mem08_new = block[511  : 448];
          w_mem09_new = block[447  : 384];
          w_mem10_new = block[383  : 320];
          w_mem11_new = block[319  : 256];
          w_mem12_new = block[255  : 192];
          w_mem13_new = block[191  : 128];
          w_mem14_new = block[127  :  64];
          w_mem15_new = block[63   :   0];
          w_mem_we    = 1;
        end

      if (next && (w_ctr_reg > 15))
        begin
          w_mem00_new = w_mem[01];
          w_mem01_new = w_mem[02];
          w_mem02_new = w_mem[03];
          w_mem03_new = w_mem[04];
          w_mem04_new = w_mem[05];
          w_mem05_new = w_mem[06];
          w_mem06_new = w_mem[07];
          w_mem07_new = w_mem[08];
          w_mem08_new = w_mem[09];
          w_mem09_new = w_mem[10];
          w_mem10_new = w_mem[11];
          w_mem11_new = w_mem[12];
          w_mem12_new = w_mem[13];
          w_mem13_new = w_mem[14];
          w_mem14_new = w_mem[15];
          w_mem15_new = w_new;
          w_mem_we    = 1;
        end
    end // w_mem_update_logic


  //----------------------------------------------------------------
  // w_ctr
  // W schedule adress counter. Counts from 0x10 to 0x3f and
  // is used to expand the block into words.
  //----------------------------------------------------------------
  always @*
    begin : w_ctr
      w_ctr_new = 7'h0;
      w_ctr_we  = 1'h0;

      if (init)
        begin
          w_ctr_new = 7'h00;
          w_ctr_we  = 1'h1;
        end

      if (next)
        begin
          w_ctr_new = w_ctr_reg + 7'h01;
          w_ctr_we  = 1'h1;
        end
    end // w_ctr

endmodule // sha512_w_mem


//----------------------------------------------------------------
// kogge_stone_64_wmem
//
// 64-bit Kogge-Stone Parallel-Prefix Adder
// Optimized: Uses OR instead of XOR for carry propagation stages.
//----------------------------------------------------------------
module kogge_stone_64_wmem (
    input wire [63:0] A,
    input wire [63:0] B,
    output wire [63:0] S
);
    wire [63:0] G0 = A & B;
    wire [63:0] P0 = A | B; // Optimized: OR gate is faster and smaller than XOR
    wire [63:0] P_sum = A ^ B; // XOR is only used for the final sum stage

    // Stage 1
    wire [63:0] G1, P1;
    assign G1[0] = G0[0];
    assign P1[0] = P0[0];
    genvar i;
    generate
        for (i = 1; i < 64; i = i + 1) begin : stage1
            assign G1[i] = G0[i] | (P0[i] & G0[i-1]);
            assign P1[i] = P0[i] & P0[i-1];
        end
    endgenerate

    // Stage 2
    wire [63:0] G2, P2;
    assign G2[1:0] = G1[1:0];
    assign P2[1:0] = P1[1:0];
    generate
        for (i = 2; i < 64; i = i + 1) begin : stage2
            assign G2[i] = G1[i] | (P1[i] & G1[i-2]);
            assign P2[i] = P1[i] & P1[i-2];
        end
    endgenerate

    // Stage 3
    wire [63:0] G3, P3;
    assign G3[3:0] = G2[3:0];
    assign P3[3:0] = P2[3:0];
    generate
        for (i = 4; i < 64; i = i + 1) begin : stage3
            assign G3[i] = G2[i] | (P2[i] & G2[i-4]);
            assign P3[i] = P2[i] & P2[i-4];
        end
    endgenerate

    // Stage 4
    wire [63:0] G4, P4;
    assign G4[7:0] = G3[7:0];
    assign P4[7:0] = P3[7:0];
    generate
        for (i = 8; i < 64; i = i + 1) begin : stage4
            assign G4[i] = G3[i] | (P3[i] & G3[i-8]);
            assign P4[i] = P3[i] & P3[i-8];
        end
    endgenerate

    // Stage 5
    wire [63:0] G5, P5;
    assign G5[15:0] = G4[15:0];
    assign P5[15:0] = P4[15:0];
    generate
        for (i = 16; i < 64; i = i + 1) begin : stage5
            assign G5[i] = G4[i] | (P4[i] & G4[i-16]);
            assign P5[i] = P4[i] & P4[i-16];
        end
    endgenerate

    // Stage 6
    wire [63:0] G6, P6;
    assign G6[31:0] = G5[31:0];
    assign P6[31:0] = P5[31:0];
    generate
        for (i = 32; i < 64; i = i + 1) begin : stage6
            assign G6[i] = G5[i] | (P5[i] & G5[i-32]);
            assign P6[i] = P5[i] & P5[i-32];
        end
    endgenerate

    // Sum
    assign S[0] = P_sum[0];
    assign S[63:1] = P_sum[63:1] ^ G6[62:0];
endmodule
//======================================================================
// EOF sha512_w_mem.v
//======================================================================
