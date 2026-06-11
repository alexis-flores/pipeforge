// Demo 04 — Two classic nkMatlib bugs for the linter to catch.
// Try:  pipeforge-cli lint 04_lint_bugs.sv
// Expect: a delay-match finding (c_0 consumed at stage 4 with no matching
// `PIPE) and a valid-chain finding (valid delayed 1 cycle while the data
// path is a 4-cycle multiply). The fix text names the exact `PIPE to add.

module demo_lint_bugs
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

// BUG 1: c_0 goes straight into the adder — it needs `PIPE(mul_pipe, ...)
logic [g.WIDTH-1:0] y_2;
add i_add_y_2 ( .g (g), .a (prod_1), .b (c_0), .f (y_2) );

// BUG 2: the valid chain uses a 1-cycle delay across the 4-cycle multiply
`PIPE(valid, , valid, 0, 1)
`PIPE(valid, , valid, 1, 2)

assign valid_N = valid_2;
assign y_N = y_2;

endmodule
