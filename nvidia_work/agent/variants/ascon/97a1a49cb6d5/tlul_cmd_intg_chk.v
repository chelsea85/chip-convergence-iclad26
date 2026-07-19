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

	// cmd payload extraction (43 bits total)
	wire [42:0] cmd;
	assign cmd[38:7]  = tl_i[90:59];  // a_address
	assign cmd[6:4]   = tl_i[106:104]; // a_opcode
	assign cmd[3:0]   = tl_i[58:55];  // a_mask
	assign cmd[42:39] = tl_i[18:15];  // a_user.instr_type

	wire [1:0] err;
	// Integrity bits for command are at tl_i[14:8]
	prim_secded_inv_64_57_dec u_chk(
		.data_i({tl_i[14:8], 14'b0, cmd}),
		.data_o(),
		.syndrome_o(),
		.err_o(err)
	);

	wire data_err;
	// tlul_data_integ_dec expects a single 39-bit port: {integrity[6:0], data[31:0]}
	tlul_data_integ_dec u_tlul_data_integ_dec(
		.data_intg_i({tl_i[6:0], tl_i[54:23]}),
		.data_err_o(data_err)
	);

	// err_o is gated by a_valid (tl_i[108])
	assign err_o = tl_i[108] & (err[1] | err[0] | data_err);

	wire unused_tl;
	assign unused_tl = |tl_i;
endmodule
