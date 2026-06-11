// Demo 03 — hand-written nkMatlib implementation of 03_pipeline.m.
// Lint-clean: operands delay-matched, valid chain correct, conventional names.
`include "macros.svh"

module demo_pipeline
  (
  fixedp g,
  input valid_0,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  input [g.WIDTH-1:0] c_0,
  output valid_N,
  output [g.WIDTH-1:0] y_N
  );

logic [g.WIDTH-1:0] prod_1;

smul i_smul_prod_1 ( .g (g), .a (a_0), .b (b_0), .f (prod_1) );

`PIPE(mul_pipe, [g.WIDTH-1:0], c, 0, 1)
`PIPE(mul_valid, , valid, 0, 1)

logic [g.WIDTH-1:0] y_2;

add i_add_y_2 ( .g (g), .a (prod_1), .b (c_1), .f (y_2) );

`PIPE(valid, , valid, 1, 2)

assign valid_N = valid_2;
assign y_N = y_2;

endmodule
