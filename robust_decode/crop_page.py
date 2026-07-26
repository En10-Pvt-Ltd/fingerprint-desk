# SPDX-License-Identifier: Apache-2.0
import sys, cv2, numpy as np
src, dst = sys.argv[1], sys.argv[2]
img = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
# Paper is the large bright region. Blur, Otsu, take largest bright component.
b = cv2.GaussianBlur(img, (0,0), 3)
_, m = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
n, lbl, stats, _ = cv2.connectedComponentsWithStats((m>0).astype(np.uint8), 8)
# largest component excluding background label 0
areas = stats[1:, cv2.CC_STAT_AREA]
k = 1 + int(np.argmax(areas))
x, y, w, h = (stats[k, cv2.CC_STAT_LEFT], stats[k, cv2.CC_STAT_TOP],
              stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT])
# inset a few percent to drop the paper edge/shadow, then crop the original
ix, iy = int(w*0.03), int(h*0.03)
x0, y0 = max(0, x+ix), max(0, y+iy)
x1, y1 = min(img.shape[1], x+w-ix), min(img.shape[0], y+h-iy)
crop = cv2.imread(src, cv2.IMREAD_COLOR)[y0:y1, x0:x1]
cv2.imwrite(dst, crop)
print(f"page bbox ({x},{y},{w},{h}) -> crop {x1-x0}x{y1-y0} saved {dst}")
