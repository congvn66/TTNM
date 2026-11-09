# PDF → positioned evidence example

- `report.pdf`: synthetic Vietnamese paragraph/table and a labelled bar chart.
- `chart-request.json`: ready question trigger selecting **only category A**.
  Its verified label annotation is a reviewed source fact, not DePlot output.
- `output/document.json`: Docling artifact with pages, 12 table values and picture candidates.
- `output/base-evidence.json`: upload-time `document-evidence-v2` batch.
- `output/chart-result.json`: on-demand batch plus original DePlot response.

The 12 table values each have a cell-level bbox and row/column headers. Chart
values are not part of the base batch. The chart request extracts one requested
value, A=50, labelled `đọc từ nhãn`, with its reviewed printed-label bbox.
Unknown table units/periods remain null rather than invented.

Run instructions and integration limitations:
[Docling/DePlot handoff](../../doc/HANDOUT/tien-docling-deplot.md).
