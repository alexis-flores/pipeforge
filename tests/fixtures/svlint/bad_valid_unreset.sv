// BAD: valid signal delayed through unreset mul_pipe -> reset
module bad_valid_unreset
  (
  fixedp g,
  input valid_0,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  output valid_N,
  output [g.WIDTH-1:0] p_N
  );

logic [g.WIDTH-1:0] p_1;
smul i_smul_p_1 ( .g (g), .a (a_0), .b (b_0), .f (p_1) );

`PIPE(mul_pipe, , valid, 0, 1)

assign valid_N = valid_1;
assign p_N = p_1;
endmodule
