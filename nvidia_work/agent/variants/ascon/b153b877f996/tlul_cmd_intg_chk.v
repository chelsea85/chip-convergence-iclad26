module tlul_cmd_intg_chk (
	tl_i,
	err_o
);
	localparam signed [31:0] prim_mubi_pkg_MuBi4Width = 4;
	localparam signed [31:0] tlul_pkg_DataIntgWidth = 7;
	localparam signed [31:0] tlul_pkg_H2DCmdIntgWidth = 7;
	localparam signed [31:0] top_pkg_TL_AUW = 23;
	localparam signed [31:0] tlul_pkg_RsvdWidth = ((top_pkg_TL_AUW - prim_mubi_pkg_MuBi4Width) - tlul_pkg_H2DCmdIntgWidth) - tlul_pkg_DataIntgWidth;
	localparam signed [31:0] top_pkg_TL_AIW = 8;
	localparam signed [31:0] top_pkg_TL_AW = 32;
	localparam signed [31:0] top_pkg_TL_DW = 32;
	localparam signed [31:0] top_pkg_TL_DBW = top_pkg_TL_DW >> 3;
	localparam signed [31:0] top_pkg_TL_SZW = $clog2($clog2(top_pkg_TL_DBW) + 1);
	input wire [((((((7 + top_pkg_TL_SZW) + top_pkg_TL_AIW) + top_pkg_TL_AW) + top_pkg_TL_DBW) + top_pkg_TL_DW) + (((tlul_pkg_RsvdWidth + prim_mubi_pkg_MuBi4Width) + tlul_pkg_H2DCmdIntgWidth) + tlul_pkg_DataIntgWidth)) + 0:0] tl_i;
	output wire err_o;

	// Simplified bit extraction for the command integrity check.
	// Based on the TL-UL H2D struct mapping:
	// a_valid    : tl_i[108]
	// a_opcode   : tl_i[107:105]
	// a_address  : tl_i[91:60]
	// a_mask     : tl_i[59:56]
	// a_user     : tl_i[23:0]
	//   .instr_type : tl_i[18:15]
	//   .cmd_intg   : tl_i[14:8]
	//   .data_intg  : tl_i[7:1]
	
	// [rtlscout-cutpoints] Declare named intermediate wires to help partition optimization.
	wire [42:0] cmd_payload;
	assign cmd_payload = {
		tl_i[18:15],  // a_user.instr_type (4 bits)
		tl_i[91:60],  // a_address (32 bits)
		tl_i[107:105],// a_opcode (3 bits)
		tl_i[59:56]   // a_mask (4 bits)
	};

	wire [6:0] cmd_intg = tl_i[14:8];
	wire [1:0] err;
	
	// SECDED decoder for command integrity.
	// Input is 64 bits: 7 bits ECC + 57 bits data.
	// cmd_payload is 43 bits, so we pad with 14 zeros.
	prim_secded_inv_64_57_dec u_chk(
		.data_i({cmd_intg, 14'b0, cmd_payload}),
		.data_o(),
		.syndrome_o(),
		.err_o(err)
	);

	// Data integrity check.
	wire [31:0] a_data = tl_i[55:24];
	wire [6:0] data_intg = tl_i[7:1];
	wire data_err;
	tlul_data_integ_dec u_tlul_data_integ_dec(
		.data_intg_i({data_intg, a_data}),
		.data_err_o(data_err)
	);

	// Final error signal is gated by a_valid.
	// [rtlscout-cutpoints] Explicit width for reduction.
	wire a_valid = tl_i[108];
	assign err_o = a_valid & (err[1] | err[0] | data_err);

	// Silence unused bits warning.
	wire unused_tl;
	assign unused_tl = ^tl_i;
endmodule
