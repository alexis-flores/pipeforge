// BAD: mul_pipe used to match a divider's latency -> delay-match
module bad_wrong_pipe
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  input [g.WIDTH-1:0] c_0,
  output [g.WIDTH-1:0] y_N
  );

logic [g.WIDTH-1:0] q_1;
sdiv i_sdiv_q_1 ( .g (g), .a (a_0), .b (b_0), .f (q_1) );

`PIPE(mul_pipe, [g.WIDTH-1:0], c, 0, 2)

logic [g.WIDTH-1:0] y_3;
add i_add_y_3 ( .g (g), .a (q_1), .b (c_2), .f (y_3) );

assign y_N = y_3;
endmodule
