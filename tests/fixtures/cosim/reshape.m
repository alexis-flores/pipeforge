% AR-4: reshape is a column-major relabel (see reshape.sv)
% x is a 24x1 vector reshaped to 8x3; the relabel is value-preserving, so the
% elementwise product compares element-for-element under the column-major map.
y = reshape(x, 8, 3);
z = y .* k;
