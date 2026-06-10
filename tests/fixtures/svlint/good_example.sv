// README example: result = A*B + C (lint-clean reference)
`include "macros.svh"

module example
  (
  fixedp g,
  input valid_0,
  input [3:1][2:1][g.WIDTH-1:0] A_0,
  input [2:1][3:1][g.WIDTH-1:0] B_0,
  input [3:1][3:1][g.WIDTH-1:0] C_0,
  output valid_N,
  output [3:1][3:1][g.WIDTH-1:0] result_N
  );

logic [3:1][3:1][g.WIDTH-1:0] prod_1;

matmul #(.A_ROWS(3), .A_COLS_B_ROWS(2), .B_COLS(3)) i_matmul_prod_1
  (
    .g (g), .a (A_0), .b (B_0), .f (prod_1)
  );

`PIPE(matmul_pipe, [3:1][3:1][g.WIDTH-1:0], C, 0, 1)
`PIPE(matmul_valid, , valid, 0, 1)

logic [3:1][3:1][g.WIDTH-1:0] result_2;

matadd #(.ROWS(3), .COLS(3)) i_matadd_result_2
  (
    .g (g), .a (prod_1), .b (C_1), .f (result_2)
  );

`PIPE(valid, , valid, 1, 2)

assign valid_N = valid_2;
assign result_N = result_2;

endmodule
