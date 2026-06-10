// BAD: two signals share stage suffix _1 but arrive at different cycles -> suffix
module bad_suffix
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  output [g.WIDTH-1:0] p_N,
  output [g.WIDTH-1:0] s_N
  );

logic [g.WIDTH-1:0] p_1;
smul i_smul_p_1 ( .g (g), .a (a_0), .b (b_0), .f (p_1) );

logic [g.WIDTH-1:0] s_1;
add i_add_s_1 ( .g (g), .a (a_0), .b (b_0), .f (s_1) );

assign p_N = p_1;
assign s_N = s_1;
endmodule
