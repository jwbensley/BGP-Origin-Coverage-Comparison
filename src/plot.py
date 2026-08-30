#!/usr/bin/env -S uv run

import json
import os
import urllib.request
import plotly.graph_objects as go  # type: ignore
import plotly.offline as po  # type: ignore
from plotly.io._utils import plotly_cdn_url  # type: ignore
from app.settings import Settings


def parse_args() -> None:
    os.makedirs(Settings.get_plot_dir(), exist_ok=True)


def ensure_plotly_js(plot_dir: str) -> None:
    """
    Download the smaller 'basic' plotly.js bundle (bar/scatter/pie only) into
    the plot directory as plotly.min.js, if it isn't already present. This is
    used instead of the ~4.9MB full plotly.js bundle since only bar charts
    are rendered here. include_plotlyjs='directory' will leave an existing
    plotly.min.js untouched, so this only downloads once.
    """
    target = os.path.join(plot_dir, "plotly.min.js")
    if os.path.exists(target):
        return

    basic_url = plotly_cdn_url().replace("plotly-", "plotly-basic-", 1)
    print(f"Downloading {basic_url} to {target}")
    urllib.request.urlretrieve(basic_url, target)


def load_json(filename: str) -> dict:
    with open(filename, "r") as f:
        return json.load(f)


def plot(
    data: dict[str, dict[str, float]],
    title: str,
    output_file: str,
) -> None:
    """
    Plot a bar chart with the given data and save it to a file
    """

    plot_dir = Settings.get_plot_dir()
    out_file = os.path.join(plot_dir, output_file)
    comparisons = list(data.keys())

    ensure_plotly_js(plot_dir)

    fig = go.Figure(
        data=[
            go.Bar(
                name=f"IPv{version}",
                x=comparisons,
                y=[
                    data[comparison][f"{version}_count"]
                    for comparison in comparisons
                ],
                text=[
                    f"{data[comparison][f'{version}_count']:,} "
                    f"({data[comparison][f'{version}_percent']:,.2f}%)"
                    for comparison in comparisons
                ],
                customdata=[
                    f"{data[comparison][f'{version}_count']:,} "
                    f"({data[comparison][f'{version}_percent']:,.2f}%)"
                    for comparison in comparisons
                ],
                hovertemplate="%{customdata}",
                textfont=dict(size=17, color="black"),
            )
            for version in (4, 6)
        ],
    )
    fig.update_layout(
        barmode="group",
        title_text=title,
        title_font=dict(size=28),
        title_x=0.5,
        legend=dict(yanchor="top", xanchor="left", x=0.01, y=1.1),
        margin=dict(l=0, r=0, b=0, t=100, pad=0),
        xaxis=dict(tickfont=dict(size=17)),
        yaxis=dict(tickfont=dict(size=17)),
    )
    po.plot(
        fig,
        image_width=1920,
        image_height=1080,
        filename=out_file,
        auto_open=False,
        include_plotlyjs="directory",
    )

    print(f"Wrote to {out_file}")


def _series(
    stats: dict[str, float],
    count_key: str,
    prefixes_v4_key: str,
    prefixes_v6_key: str,
) -> dict[str, float]:
    """
    Build a single plot() series entry (4/6 count + percent) from the stats
    dict, using count_key for the numerator and prefixes_v4_key/
    prefixes_v6_key for the denominator.
    """
    return {
        "4_count": stats[f"{count_key}_v4"],
        "4_percent": (stats[f"{count_key}_v4"] / stats[prefixes_v4_key]) * 100,
        "6_count": stats[f"{count_key}_v6"],
        "6_percent": (stats[f"{count_key}_v6"] / stats[prefixes_v6_key]) * 100,
    }


def main() -> None:
    parse_args()
    stats = load_json(Settings.get_stats_file())

    plot(
        {
            "DFZ origins matching IRR origins": _series(
                stats,
                "dfz_irr_origin_matches",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
            "DFZ origins not matching IRR origins": _series(
                stats,
                "dfz_irr_origin_mismatches",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
            "DFZ prefixes not found in the IRR": _series(
                stats,
                "dfz_irr_prefix_not_found",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
        },
        "DFZ prefix origins compared to IRR data",
        "plot_dfz_irr.html",
    )

    plot(
        {
            "DFZ origins matching ROA origins": _series(
                stats,
                "dfz_roa_origin_matches",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
            "DFZ origins not matching ROA origins": _series(
                stats,
                "dfz_roa_origin_mismatches",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
            "DFZ prefixes not found in the RPKI": _series(
                stats,
                "dfz_roa_prefix_not_found",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
        },
        "DFZ prefix origins compared to ROA data",
        "plot_dfz_roa.html",
    )

    plot(
        {
            "IRR origins matching DFZ origins": _series(
                stats,
                "irr_dfz_origin_matches",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
            "IRR origins not matching DFZ origins": _series(
                stats,
                "irr_dfz_origin_mismatches",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
            "IRR prefixes not found in the DFZ": _series(
                stats,
                "irr_dfz_prefix_not_found",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
        },
        "IRR prefix origins compared to DFZ data",
        "plot_irr_dfz.html",
    )

    plot(
        {
            "IRR origins matching ROA origins": _series(
                stats,
                "irr_roa_origin_matches",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
            "IRR origins not matching ROA origins": _series(
                stats,
                "irr_roa_origin_mismatches",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
            "IRR prefixes not found in the RPKI": _series(
                stats,
                "irr_roa_prefix_not_found",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
        },
        "IRR prefix origins compared to ROA data",
        "plot_irr_roa.html",
    )

    plot(
        {
            "ROA origins matching DFZ origins": _series(
                stats,
                "roa_dfz_origin_matches",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
            "ROA origins not matching DFZ origins": _series(
                stats,
                "roa_dfz_origin_mismatches",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
            "ROA prefixes not found in the DFZ": _series(
                stats,
                "roa_dfz_prefix_not_found",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
        },
        "ROA prefix origins compared to DFZ data",
        "plot_roa_dfz.html",
    )

    plot(
        {
            "ROA origins matching IRR origins": _series(
                stats,
                "roa_irr_origin_matches",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
            "ROA origins not matching IRR origins": _series(
                stats,
                "roa_irr_origin_mismatches",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
            "ROA prefixes not found in the IRR": _series(
                stats,
                "roa_irr_prefix_not_found",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
        },
        "ROA prefix origins compared to IRR data",
        "plot_roa_irr.html",
    )


if __name__ == "__main__":
    main()
