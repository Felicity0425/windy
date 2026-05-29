"""Render the teacher discussion markdown into a PDF with embedded images.

This is a lightweight local renderer based on matplotlib's PdfPages, suitable
for the current environment without pandoc/weasyprint/reportlab.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib import font_manager, rcParams


BASE = Path("/data/LFT-W02_data/pengxu")
MD_PATH = BASE / "report/老师讨论稿_空地一体协同感知三维风场重构项目全景说明_20260524.md"
PDF_PATH = BASE / "report/老师讨论稿_空地一体协同感知三维风场重构项目全景说明_20260524.pdf"
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


IMAGE_PATHS = [
    BASE / "teacher_discussion_assets/stage1_summary_and_wind_distribution.png",
    BASE / "teacher_discussion_assets/stage1_trajectory_map_and_window_rows.png",
    BASE / "teacher_discussion_assets/stage2_voxel_statistics.png",
    BASE / "teacher_discussion_assets/stage2_radar_and_wind_voxels.png",
    BASE / "teacher_discussion_assets/stage3_agent_edge_statistics.png",
    BASE / "teacher_discussion_assets/stage3_sparse_graph_example.png",
    BASE / "stage4_visualizations/stage4_output_v2_representative/01376_20260129114200.png",
    BASE / "stage4_visualizations/stage4_output_v2_representative/01376_20260129114200_3d.png",
    BASE / "stage4_visualizations/stage4_output_v2_geo_representative/01376_20260129114200_country_roi.png",
    BASE / "stage4_visualizations/stage4_output_v2_geo_representative/01376_20260129114200_roi_3d.png",
    BASE / "stage5_output_v1_no_background_keyframes/01376_20260129114200_stage5_roi_3d.png",
    BASE / "stage5_visualizations/historical_gfs_keyframes_comparison/20260129114200_stage4_stage5_background_3d.png",
    BASE / "stage5_visualizations/historical_gfs_keyframes_comparison/20260129114200_stage5_minus_background_3d.png",
    BASE / "stage5_visualizations/stage5_internal_bg_test_comparison/20260206174200_stage4_stage5_background_3d.png",
]


def _setup_font() -> None:
    if Path(FONT_PATH).exists():
        font_manager.fontManager.addfont(FONT_PATH)
        rcParams["font.family"] = "Noto Sans CJK JP"
    rcParams["axes.unicode_minus"] = False


def _paginate_text(text: str, chars_per_page: int = 1700) -> list[str]:
    lines = text.splitlines()
    pages: list[str] = []
    current: list[str] = []
    count = 0
    for line in lines:
        line_len = max(1, len(line))
        if count + line_len > chars_per_page and current:
            pages.append("\n".join(current))
            current = []
            count = 0
        current.append(line)
        count += line_len
    if current:
        pages.append("\n".join(current))
    return pages


def _render_text_page(pdf: PdfPages, text: str) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = fig.add_axes([0.05, 0.03, 0.90, 0.94])
    ax.axis("off")
    ax.text(
        0.0,
        1.0,
        text,
        ha="left",
        va="top",
        fontsize=10.5,
        linespacing=1.45,
        wrap=True,
        family=rcParams["font.family"],
    )
    pdf.savefig(fig)
    plt.close(fig)


def _render_image_page(pdf: PdfPages, path: Path) -> None:
    if not path.exists():
        return
    img = mpimg.imread(path)
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = fig.add_axes([0.05, 0.08, 0.90, 0.84])
    ax.imshow(img)
    ax.axis("off")
    fig.text(0.05, 0.95, path.name, fontsize=12, ha="left", va="top")
    pdf.savefig(fig)
    plt.close(fig)


def main() -> None:
    _setup_font()
    text = MD_PATH.read_text(encoding="utf-8")
    pages = _paginate_text(text)
    with PdfPages(PDF_PATH) as pdf:
        for page in pages:
            _render_text_page(pdf, page)
        for path in IMAGE_PATHS:
            _render_image_page(pdf, path)
    print(str(PDF_PATH))


if __name__ == "__main__":
    main()
