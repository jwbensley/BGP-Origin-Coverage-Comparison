#!/usr/bin/env -S uv run

import json
import os
import urllib.request
import warnings
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
    font_size = 35
    title_size = 40

    ensure_plotly_js(plot_dir)

    fig = go.Figure(
        data=[
            go.Bar(
                name=f"IPv{version}",
                x=comparisons,
                y=[
                    data[comparison][f"{version}_percent"]
                    for comparison in comparisons
                ],
                text=[
                    f"{data[comparison][f'{version}_percent']:,.2f}%<br>"
                    f"({data[comparison][f'{version}_count']:,})"
                    for comparison in comparisons
                ],
                customdata=[
                    f"{data[comparison][f'{version}_percent']:,.2f}%<br>"
                    f"({data[comparison][f'{version}_count']:,})"
                    for comparison in comparisons
                ],
                hovertemplate="%{customdata}",
                textfont=dict(size=font_size, color="black"),
            )
            for version in (4, 6)
        ],
    )
    fig.update_layout(
        barmode="group",
        title_text=title,
        title_font=dict(size=title_size),
        title_x=0.5,
        legend=dict(
            yanchor="top",
            xanchor="left",
            x=0.01,
            y=1.1,
            font=dict(size=font_size),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, b=0, t=100, pad=0),
        xaxis=dict(tickfont=dict(size=font_size)),
        yaxis=dict(tickfont=dict(size=font_size), range=[0, 100]),
    )
    # The first two comparisons (origin matches/mismatches) are related, the
    # last one (prefixes not found) is not. Category positions are 0, 1, 2...
    # so draw a dashed separator half way between the last two.
    fig.add_vline(
        x=len(comparisons) - 1.5,
        line_dash="dash",
        line_width=3,
        line_color="grey",
    )
    filename = f"{out_file}.html"
    po.plot(
        fig,
        image_width=1920,
        image_height=1080,
        filename=filename,
        auto_open=False,
        include_plotlyjs="directory",
        config={"toImageButtonOptions": {"filename": title}},
    )
    print(f"Wrote to {filename}")

    filename = f"{out_file}.png"
    with warnings.catch_warnings():
        # Kaleido < 1.0.0 is deprecated in plotly but still works fine.
        # Older Kaleido is used because newer versions require that Chromium be installed separately, which is not guaranteed in all environments.
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message=r"\s*Support for Kaleido versions less than 1\.0\.0",
        )
        fig.write_image(filename, width=1920, height=1080)
    print(f"Wrote to {filename}")


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


def _origin_series(
    stats: dict[str, float],
    matches_key: str,
    mismatches_key: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Build the matches/mismatches plot() series entries, using their combined
    count (not the total prefix count) as the percentage denominator so the
    two bars for a given IP version add up to 100%.
    """
    matches_v4 = stats[f"{matches_key}_v4"]
    matches_v6 = stats[f"{matches_key}_v6"]
    mismatches_v4 = stats[f"{mismatches_key}_v4"]
    mismatches_v6 = stats[f"{mismatches_key}_v6"]
    total_v4 = matches_v4 + mismatches_v4
    total_v6 = matches_v6 + mismatches_v6

    matches = {
        "4_count": matches_v4,
        "4_percent": (matches_v4 / total_v4) * 100,
        "6_count": matches_v6,
        "6_percent": (matches_v6 / total_v6) * 100,
    }
    mismatches = {
        "4_count": mismatches_v4,
        "4_percent": (mismatches_v4 / total_v4) * 100,
        "6_count": mismatches_v6,
        "6_percent": (mismatches_v6 / total_v6) * 100,
    }
    return matches, mismatches


def main() -> None:
    parse_args()
    stats = load_json(Settings.get_stats_file())

    dfz_irr_matches, dfz_irr_mismatches = _origin_series(
        stats, "dfz_irr_origin_matches", "dfz_irr_origin_mismatches"
    )
    plot(
        {
            "DFZ origins matching IRR origins": dfz_irr_matches,
            "DFZ origins not matching IRR origins": dfz_irr_mismatches,
            "DFZ prefixes not found in the IRR": _series(
                stats,
                "dfz_irr_prefix_not_found",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
        },
        "DFZ prefix origins compared to IRR data",
        "DFZ prefix origins compared to IRR data",
    )

    dfz_roa_matches, dfz_roa_mismatches = _origin_series(
        stats, "dfz_roa_origin_matches", "dfz_roa_origin_mismatches"
    )
    plot(
        {
            "DFZ origins matching ROA origins": dfz_roa_matches,
            "DFZ origins not matching ROA origins": dfz_roa_mismatches,
            "DFZ prefixes not found in the RPKI": _series(
                stats,
                "dfz_roa_prefix_not_found",
                "dfz_prefixes_v4",
                "dfz_prefixes_v6",
            ),
        },
        "DFZ prefix origins compared to ROA data",
        "DFZ prefix origins compared to ROA data",
    )

    irr_dfz_matches, irr_dfz_mismatches = _origin_series(
        stats, "irr_dfz_origin_matches", "irr_dfz_origin_mismatches"
    )
    plot(
        {
            "IRR origins matching DFZ origins": irr_dfz_matches,
            "IRR origins not matching DFZ origins": irr_dfz_mismatches,
            "IRR prefixes not found in the DFZ": _series(
                stats,
                "irr_dfz_prefix_not_found",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
        },
        "IRR prefix origins compared to DFZ data",
        "IRR prefix origins compared to DFZ data",
    )

    irr_roa_matches, irr_roa_mismatches = _origin_series(
        stats, "irr_roa_origin_matches", "irr_roa_origin_mismatches"
    )
    plot(
        {
            "IRR origins matching ROA origins": irr_roa_matches,
            "IRR origins not matching ROA origins": irr_roa_mismatches,
            "IRR prefixes not found in the RPKI": _series(
                stats,
                "irr_roa_prefix_not_found",
                "irr_prefixes_v4",
                "irr_prefixes_v6",
            ),
        },
        "IRR prefix origins compared to ROA data",
        "IRR prefix origins compared to ROA data",
    )

    roa_dfz_matches, roa_dfz_mismatches = _origin_series(
        stats, "roa_dfz_origin_matches", "roa_dfz_origin_mismatches"
    )
    plot(
        {
            "ROA origins matching DFZ origins": roa_dfz_matches,
            "ROA origins not matching DFZ origins": roa_dfz_mismatches,
            "ROA prefixes not found in the DFZ": _series(
                stats,
                "roa_dfz_prefix_not_found",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
        },
        "ROA prefix origins compared to DFZ data",
        "ROA prefix origins compared to DFZ data",
    )

    roa_irr_matches, roa_irr_mismatches = _origin_series(
        stats, "roa_irr_origin_matches", "roa_irr_origin_mismatches"
    )
    plot(
        {
            "ROA origins matching IRR origins": roa_irr_matches,
            "ROA origins not matching IRR origins": roa_irr_mismatches,
            "ROA prefixes not found in the IRR": _series(
                stats,
                "roa_irr_prefix_not_found",
                "roa_prefixes_v4",
                "roa_prefixes_v6",
            ),
        },
        "ROA prefix origins compared to IRR data",
        "ROA prefix origins compared to IRR data",
    )


if __name__ == "__main__":
    main()
