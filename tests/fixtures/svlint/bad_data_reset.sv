// BAD: data signal delayed through reset mul_valid -> reset (blocks SRL inference)
module bad_data_reset
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  input [g.WIDTH-1:0] c_0,
  output [g.WIDTH-1:0] y_N
  );

logic [g.WIDTH-1:0] prod_1;
smul i_smul_prod_1 ( .g (g), .a (a_0), .b (b_0), .f (prod_1) );

`PIPE(mul_valid, [g.WIDTH-1:0], c, 0, 1)

logic [g.WIDTH-1:0] y_2;
add i_add_y_2 ( .g (g), .a (prod_1), .b (c_1), .f (y_2) );

assign y_N = y_2;
endmodule
