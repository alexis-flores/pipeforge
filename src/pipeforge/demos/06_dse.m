% Demo 06 — Design-space exploration: pick WIDTH/SCALE with data.
% Try:  pipeforge-cli dse 06_dse.m --widths 12,16,20 --scales 8,12,14
% (GUI: open this file, Exploration view, Run sweep, click a starred Pareto
%  row, Adopt selected.)
% Expect: latency climbs steeply with WIDTH+SCALE — the divider costs
% WIDTH+SCALE cycles and sqrt WIDTH-LEFT/2. Worst-case error stays large at
% every point because the stimulus leads with corner vectors (zeros, +/-max)
% that overflow any narrow format — that is the honest worst case; the
% relative trade between points is what the Pareto front shows.

g2  = gin .* gin;
n   = sqrt(g2 + bias);
out = gin ./ n;
