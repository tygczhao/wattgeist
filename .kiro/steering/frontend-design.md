---
inclusion: fileMatch
fileMatchPattern: ["frontend/src/**/*.tsx", "frontend/src/**/*.ts", "frontend/src/**/*.css"]
---

# Frontend design rules

## Theme

- Dark "haunted manor" surface `#16141d`, cards `#1f1c29`, hairlines `#2e2a3b`. Light theme is a selected
  palette from the same ramps, not an inverted filter.
- Text uses text tokens only (primary `#f2eee6`, secondary `#c4bdd0`, muted `#9a92a8`). Never colour text with a
  series colour; put a swatch or line key beside it.
- Categorical slots (validated with the dataviz validator, adjacent pairs, both modes):
  dark `#d95926 #3987e5 #199e70 #c98500 #d55181 #008300 #9085e9 #e66767`,
  light `#eb6834 #2a78d6 #1baf7a #eda100 #e87ba4 #008300 #6250d6 #e34948`.
  Light slots 3–5 are below 3:1 on the light surface, so charts using them must show direct labels or a table view.
- Heatmap: one-hue orange sequential ramp, near-zero recedes into the surface, with a scale legend.

## Charts

- 2px lines, bars at most 24px thick with 4px rounded data ends, hairline solid gridlines, 8px end dots with a 2px
  surface ring.
- One y-axis per chart. Watts and pounds never share an axis.
- Every chart has hover (crosshair on lines, per-mark on bars and cells) and a "table" toggle with the same values.
- Tooltips show the value first, label second. Insert data strings with `textContent` (React does this by default;
  never use `dangerouslySetInnerHTML`).

## Copy

- Sentence case. One spooky phrase per screen at most ("The vampire in your walls draws 114 W").
- Numbers: W with no decimals above 10 W, kWh with one decimal, money with two decimals and the currency symbol.
