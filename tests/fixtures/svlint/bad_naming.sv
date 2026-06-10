// BAD: instance name does not follow i_<module>_<signal>_<stage> -> naming
module bad_naming
  (
  fixedp g,
  input [g.WIDTH-1:0] a_0,
  input [g.WIDTH-1:0] b_0,
  output [g.WIDTH-1:0] p_N
  );

logic [g.WIDTH-1:0] p_1;
smul mult_unit ( .g (g), .a (a_0), .b (b_0), .f (p_1) );

assign p_N = p_1;
endmodule
