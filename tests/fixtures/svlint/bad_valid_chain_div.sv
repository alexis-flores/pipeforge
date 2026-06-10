// BAD: divider data path matched with mul_valid -> valid-chain
module bad_valid_chain_div
  (
  fixedp g,
  input valid_0,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  output valid_N,
  output [g.WIDTH-1:0] q_N
  );

logic [g.WIDTH-1:0] q_1;
sdiv i_sdiv_q_1 ( .g (g), .a (a_0), .b (b_0), .f (q_1) );

`PIPE(mul_valid, , valid, 0, 1)

assign valid_N = valid_1;
assign q_N = q_1;
endmodule
