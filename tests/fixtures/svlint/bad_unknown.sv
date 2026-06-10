// BAD: unknown operator module -> unknown-module
module bad_unknown
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  output [g.WIDTH-1:0] y_N
  );

logic [g.WIDTH-1:0] y_1;
magic_block i_magic_block_y_1 ( .g (g), .a (a_0), .f (y_1) );

assign y_N = y_1;
endmodule
