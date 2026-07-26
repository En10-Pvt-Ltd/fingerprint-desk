# SPDX-License-Identifier: Apache-2.0
import sys, cv2, numpy as np
sys.path.insert(0, r"D:/Work/Projects/GitHub/Forensic Fingerprinting")
from decode import segment_lines, deskew
src, dst = sys.argv[1], sys.argv[2]
gray = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
# Estimate paper brightness with a large grayscale morphological closing
# (removes thin dark text, leaves the illumination field), then flat-field.
k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k)
norm = np.clip(gray.astype(np.float64) / np.maximum(bg, 1) * 255.0, 0, 255).astype(np.uint8)
cv2.imwrite(dst, norm)
# Diagnostic: how many lines does the decoder now segment?
d, ang = deskew(norm)
print(f"flat-fielded -> {dst}; deskew {ang:+.2f}, lines found = {len(segment_lines(d))}")
