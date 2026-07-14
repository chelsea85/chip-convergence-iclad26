//======================================================================
//
// sha512_k_constants.v
// --------------------
// The table K with constants in the SHA-512 hash function.
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

module sha512_k_constants(
                          input wire  [6 : 0]  addr,
                          output wire [63 : 0] K
                         );

  //----------------------------------------------------------------
  // Wires.
  //----------------------------------------------------------------
  reg [63 : 0] tmp_K;
  reg [63 : 0] k_group [0 : 4];


  //----------------------------------------------------------------
  // Concurrent connectivity for ports etc.
  //----------------------------------------------------------------
  assign K = tmp_K;


  //----------------------------------------------------------------
  // addr_mux
  //----------------------------------------------------------------
  always @*
    begin : addr_mux
      case(addr[3:0])
        0:  k_group[0] = 64'h428a2f98d728ae22;
        1:  k_group[0] = 64'h7137449123ef65cd;
        2:  k_group[0] = 64'hb5c0fbcfec4d3b2f;
        3:  k_group[0] = 64'he9b5dba58189dbbc;
        4:  k_group[0] = 64'h3956c25bf348b538;
        5:  k_group[0] = 64'h59f111f1b605d019;
        6:  k_group[0] = 64'h923f82a4af194f9b;
        7:  k_group[0] = 64'hab1c5ed5da6d8118;
        8:  k_group[0] = 64'hd807aa98a3030242;
        9:  k_group[0] = 64'h12835b0145706fbe;
        10: k_group[0] = 64'h243185be4ee4b28c;
        11: k_group[0] = 64'h550c7dc3d5ffb4e2;
        12: k_group[0] = 64'h72be5d74f27b896f;
        13: k_group[0] = 64'h80deb1fe3b1696b1;
        14: k_group[0] = 64'h9bdc06a725c71235;
        15: k_group[0] = 64'hc19bf174cf692694;
      endcase

      case(addr[3:0])
        0:  k_group[1] = 64'he49b69c19ef14ad2;
        1:  k_group[1] = 64'hefbe4786384f25e3;
        2:  k_group[1] = 64'h0fc19dc68b8cd5b5;
        3:  k_group[1] = 64'h240ca1cc77ac9c65;
        4:  k_group[1] = 64'h2de92c6f592b0275;
        5:  k_group[1] = 64'h4a7484aa6ea6e483;
        6:  k_group[1] = 64'h5cb0a9dcbd41fbd4;
        7:  k_group[1] = 64'h76f988da831153b5;
        8:  k_group[1] = 64'h983e5152ee66dfab;
        9:  k_group[1] = 64'ha831c66d2db43210;
        10: k_group[1] = 64'hb00327c898fb213f;
        11: k_group[1] = 64'hbf597fc7beef0ee4;
        12: k_group[1] = 64'hc6e00bf33da88fc2;
        13: k_group[1] = 64'hd5a79147930aa725;
        14: k_group[1] = 64'h06ca6351e003826f;
        15: k_group[1] = 64'h142929670a0e6e70;
      endcase

      case(addr[3:0])
        0:  k_group[2] = 64'h27b70a8546d22ffc;
        1:  k_group[2] = 64'h2e1b21385c26c926;
        2:  k_group[2] = 64'h4d2c6dfc5ac42aed;
        3:  k_group[2] = 64'h53380d139d95b3df;
        4:  k_group[2] = 64'h650a73548baf63de;
        5:  k_group[2] = 64'h766a0abb3c77b2a8;
        6:  k_group[2] = 64'h81c2c92e47edaee6;
        7:  k_group[2] = 64'h92722c851482353b;
        8:  k_group[2] = 64'ha2bfe8a14cf10364;
        9:  k_group[2] = 64'ha81a664bbc423001;
        10: k_group[2] = 64'hc24b8b70d0f89791;
        11: k_group[2] = 64'hc76c51a30654be30;
        12: k_group[2] = 64'hd192e819d6ef5218;
        13: k_group[2] = 64'hd69906245565a910;
        14: k_group[2] = 64'hf40e35855771202a;
        15: k_group[2] = 64'h106aa07032bbd1b8;
      endcase

      case(addr[3:0])
        0:  k_group[3] = 64'h19a4c116b8d2d0c8;
        1:  k_group[3] = 64'h1e376c085141ab53;
        2:  k_group[3] = 64'h2748774cdf8eeb99;
        3:  k_group[3] = 64'h34b0bcb5e19b48a8;
        4:  k_group[3] = 64'h391c0cb3c5c95a63;
        5:  k_group[3] = 64'h4ed8aa4ae3418acb;
        6:  k_group[3] = 64'h5b9cca4f7763e373;
        7:  k_group[3] = 64'h682e6ff3d6b2b8a3;
        8:  k_group[3] = 64'h748f82ee5defb2fc;
        9:  k_group[3] = 64'h78a5636f43172f60;
        10: k_group[3] = 64'h84c87814a1f0ab72;
        11: k_group[3] = 64'h8cc702081a6439ec;
        12: k_group[3] = 64'h90befffa23631e28;
        13: k_group[3] = 64'ha4506cebde82bde9;
        14: k_group[3] = 64'hbef9a3f7b2c67915;
        15: k_group[3] = 64'hc67178f2e372532b;
      endcase

      case(addr[3:0])
        0:  k_group[4] = 64'hca273eceea26619c;
        1:  k_group[4] = 64'hd186b8c721c0c207;
        2:  k_group[4] = 64'heada7dd6cde0eb1e;
        3:  k_group[4] = 64'hf57d4f7fee6ed178;
        4:  k_group[4] = 64'h06f067aa72176fba;
        5:  k_group[4] = 64'h0a637dc5a2c898a6;
        6:  k_group[4] = 64'h113f9804bef90dae;
        7:  k_group[4] = 64'h1b710b35131c471b;
        8:  k_group[4] = 64'h28db77f523047d84;
        9:  k_group[4] = 64'h32caab7b40c72493;
        10: k_group[4] = 64'h3c9ebe0a15c9bebc;
        11: k_group[4] = 64'h431d67c49c100d4c;
        12: k_group[4] = 64'h4cc5d4becb3e42b6;
        13: k_group[4] = 64'h597f299cfc657e2a;
        14: k_group[4] = 64'h5fcb6fab3ad6faec;
        15: k_group[4] = 64'h6c44198c4a475817;
      endcase

      case(addr[6:4])
        0: tmp_K = k_group[0];
        1: tmp_K = k_group[1];
        2: tmp_K = k_group[2];
        3: tmp_K = k_group[3];
        4: tmp_K = k_group[4];
        default: tmp_K = 64'h0;
      endcase
    end // block: addr_mux
endmodule // sha512_k_constants
