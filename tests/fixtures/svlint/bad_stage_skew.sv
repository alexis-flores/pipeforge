// BAD: operands taken from stages one cycle apart -> delay-match
module bad_stage_skew
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  output [g.WIDTH-1:0] t_N
  );

logic [g.WIDTH-1:0] u_1;
smul i_smul_u_1 ( .g (g), .a (a_0), .b (b_0), .f (u_1) );

logic [g.WIDTH-1:0] v_1;
smul i_smul_v_1 ( .g (g), .a (b_0), .b (a_0), .f (v_1) );

logic [g.WIDTH-1:0] s_2;
add i_add_s_2 ( .g (g), .a (u_1), .b (v_1), .f (s_2) );

logic [g.WIDTH-1:0] t_3;
add i_add_t_3 ( .g (g), .a (s_2), .b (u_1), .f (t_3) );

assign t_N = t_3;
endmodule
